// SPDX-License-Identifier: Apache-2.0
//
// `MapSugar`: the `.map(f)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that replaces each element with the closure's const value. Bails
// (None) on an opaque element (no const value), a runtime/overflowing closure, or a
// mapped value it cannot materialize back to an `Expr`. Lifted verbatim from the
// `Adaptor::Map(closure)` arm of the former `apply_one_adaptor` match.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, Pat, Type};

use crate::sugar::factory::{
    desugar_build_ctx, CompositeFloor, SugarBody, SugarBuildCtx, TermFloor,
};
use crate::sugar::sequence_floor::{sequence_elem_term_floor, sequence_value_term_floor};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::temporal_floor::{
    CollectionIterMember, IterFloor, IterStanding, MapOutputIterMember, TemporalFloorRefusal,
};
use crate::sugar::term_dispatch::{CurryVisitor, DesugaredFloorAccept};
use crate::sugar::{format::stable_let_bindings, method_family};
use crate::{
    canonical_term_sig, closure_body_mutates_captured_runtime_state, const_eval_unary_closure,
    const_eval_unary_closure_with_u128_shift, curry_param_name, curry_param_term,
    strip_refs_groups, substitute_expr, token_key, ConstVal, Desugared, DesugaredElem, Effect,
    Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "map",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                fn x(n: i32) -> i32 { n * 2 }

                #[test]
                fn t_map_good() {
                    let _map_owner = [1i32, 1].into_iter().map(|n| x(n));
                    let got = [1i32, 1].into_iter().map(|n| x(n)).sum::<i32>();
                    assert_eq!(got, x(1) + x(1));
                }
            "#,
            r#"
                fn x(n: i32) -> i32 { n * 2 }

                #[test]
                fn t_map_bad() {
                    let _map_owner = [1i32, 1].into_iter().map(|n| x(n));
                    let got = [1i32, 1].into_iter().map(|n| x(n)).sum::<i32>();
                    assert_eq!(got, x(1) + x(1) + 1);
                }
            "#,
        ),
        recognize_composite,
    );
pub(crate) const TERM_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "map_term",
        crate::sugar::claim::SugarWitnesses::temporal_campaign(
            "S5 adapter family: map term projection",
        ),
        recognize_term,
    );

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "map" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(f) = &call.args[0] else {
        return None;
    };
    if !crate::resolves_literal_sequence_in_scope(&call.receiver, fcx) {
        return None;
    }
    Some(Box::new(MapCallSugar {
        inner: SugarBody::from_node(method_family::build_literal_sequence_composite(
            &call.receiver,
            fcx,
        )?),
        mapper: MapClosure::build(
            f.clone(),
            fcx,
            receiver_has_unsigned_count_ones_range(&call.receiver),
        )?,
    }))
}

pub(crate) fn recognize_term(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "map" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(f) = &call.args[0] else {
        return None;
    };
    if !crate::resolves_literal_sequence_in_scope(&call.receiver, fcx) {
        return None;
    }
    Some(Box::new(MapTermSugar {
        inner: SugarBody::from_node(method_family::build_literal_sequence_composite(
            &call.receiver,
            fcx,
        )?),
        mapper: MapClosure::build(
            f.clone(),
            fcx,
            receiver_has_unsigned_count_ones_range(&call.receiver),
        )?,
    }))
}

pub(crate) struct MapClosure {
    expr: syn::ExprClosure,
    term_binding: Option<MapTermBinding>,
    u128_shift_hint: bool,
}

struct MapTermBinding {
    param: String,
    curry_param: String,
    body: SugarBody<TermFloor>,
}

impl MapClosure {
    pub(crate) fn build(
        expr: syn::ExprClosure,
        fcx: &SugarBuildCtx,
        u128_shift_hint: bool,
    ) -> Option<Self> {
        if expr.inputs.len() != 1 {
            return None;
        }
        let term_binding = closure_single_param_name(&expr)
            .or_else(|| {
                closure_single_wildcard_literal_sequence(&expr, fcx).then(|| "_".to_string())
            })
            .map(|param| {
                let curry_param = curry_param_name(&param);
                let body_scope = fcx
                    .scope()
                    .fork_with_stable_term_binding(&param, curry_param_term(&param));
                let body_fcx = fcx.with_scope(&body_scope);
                let body = SugarBody::<TermFloor>::term(expr.body.as_ref(), &body_fcx);
                MapTermBinding {
                    param,
                    curry_param,
                    body,
                }
            });
        Some(Self {
            expr,
            term_binding,
            u128_shift_hint,
        })
    }

    fn expr(&self) -> &syn::ExprClosure {
        &self.expr
    }

    fn substituted_body_for(&self, value: &ConstVal) -> Option<Expr> {
        if self.expr.inputs.len() != 1 {
            return None;
        }
        let tail = closure_tail_expr(&self.expr)?;
        let mut bindings = BTreeMap::new();
        bind_expr_closure_arg(&self.expr.inputs[0], value, &mut bindings)?;
        Some(substitute_expr(tail, &bindings))
    }
}

/// A source-level `.map(..)` site. It captures the raw receiver and builds the
/// sequence child lazily in `desugar`, once the full scope is available.
struct MapCallSugar {
    inner: SugarBody<CompositeFloor>,
    mapper: MapClosure,
}

impl Sugar for MapCallSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(outcome) = captured_mutation_refusal(&self.mapper) {
            return outcome;
        }
        let mapped = match reduce_map_body(&self.inner, &self.mapper, ctx) {
            Ok(mapped) => mapped,
            Err(outcome) => return outcome,
        };
        Outcome::Complete(mapped.into_desugared())
    }
}

/// Replace each element with the const value of `f` applied to it.
pub(crate) struct MapSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) mapper: MapClosure,
}

impl Sugar for MapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(outcome) = captured_mutation_refusal(&self.mapper) {
            return outcome;
        }
        match reduce_map_body(&self.inner, &self.mapper, ctx) {
            Ok(mapped) => Outcome::Complete(mapped.into_desugared()),
            Err(outcome) => outcome,
        }
    }
}

pub(crate) struct MapTermSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) mapper: MapClosure,
}

impl Sugar for MapTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(outcome) = captured_mutation_refusal(&self.mapper) {
            return outcome;
        }
        let mapped = match reduce_map_body(&self.inner, &self.mapper, ctx) {
            Ok(mapped) => mapped,
            Err(outcome) => return outcome,
        };
        Outcome::Complete(Desugared::TermSeq(mapped.into_terms()))
    }
}

enum MappedSequence {
    Values(Vec<DesugaredElem>),
    Terms(Vec<Rc<Term>>),
}

enum MapReceiverSequence {
    Values(Vec<DesugaredElem>),
    Terms(Vec<Rc<Term>>),
}

#[derive(Default)]
struct MapFloor {
    iter: IterFloor,
}

struct MapFloorOutput<T> {
    mapped: Vec<T>,
    standing: IterStanding,
}

impl<T> MapFloorOutput<T> {
    fn into_mapped(self) -> Vec<T> {
        self.mapped
    }

    fn standing(&self) -> &IterStanding {
        &self.standing
    }
}

impl MapFloor {
    fn derived_operand(&self, count: usize) -> Result<IterStanding, Outcome> {
        self.iter
            .alias(&CollectionIterMember::derived(count))
            .map_err(map_floor_refusal)
    }

    fn desugar<I, T, U, F>(
        &self,
        operand: IterStanding,
        items: I,
        mut mapper: F,
    ) -> Result<MapFloorOutput<U>, Outcome>
    where
        I: IntoIterator<Item = T>,
        F: FnMut(usize, T) -> Result<U, Outcome>,
    {
        let mapped = items
            .into_iter()
            .enumerate()
            .map(|(idx, item)| mapper(idx, item))
            .collect::<Result<Vec<_>, _>>()?;
        if mapped.len() != operand.count() {
            return Err(Outcome::Incomplete(Effect::CoverageGap {
                boundary: "Iterator::map".to_string(),
                reason: format!(
                    "temporal map floor count mismatch: operand standing had {} tick(s), \
                     real map produced {} tick(s); refused",
                    operand.count(),
                    mapped.len()
                ),
            }));
        }
        let standing = self
            .iter
            .alias(&MapOutputIterMember::new(mapped.len()))
            .map_err(map_floor_refusal)?;
        Ok(MapFloorOutput { mapped, standing })
    }
}

impl MappedSequence {
    fn into_desugared(self) -> Desugared {
        match self {
            MappedSequence::Values(values) => Desugared::Seq(values),
            MappedSequence::Terms(terms) => Desugared::TermSeq(terms),
        }
    }

    fn into_terms(self) -> Vec<Rc<Term>> {
        match self {
            MappedSequence::Values(values) => values
                .iter()
                .map(|elem| {
                    elem.value
                        .as_ref()
                        .and_then(sequence_value_term_floor)
                        .unwrap_or_else(|| map_gap("literal map value did not reify to a term"))
                })
                .collect(),
            MappedSequence::Terms(terms) => terms,
        }
    }
}

fn captured_mutation_refusal(mapper: &MapClosure) -> Option<Outcome> {
    let source = Expr::Closure(mapper.expr().clone());
    if !closure_body_mutates_captured_runtime_state(&source) {
        return None;
    }
    Some(Outcome::Incomplete(Effect::Mutation {
        boundary: token_key(&source),
    }))
}

fn reduce_map_body(
    inner: &SugarBody<CompositeFloor>,
    mapper: &MapClosure,
    ctx: &SugarCtx,
) -> Result<MappedSequence, Outcome> {
    let seq = match inner.reduce(ctx) {
        Outcome::Complete(Desugared::Seq(seq)) => MapReceiverSequence::Values(seq),
        Outcome::Complete(Desugared::TermSeq(terms)) => MapReceiverSequence::Terms(terms),
        Outcome::Complete(_) => map_gap("map receiver reduced to non-sequence"),
        Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
    };
    reduce_map_sequence(seq, mapper, ctx)
}

fn reduce_map_sequence(
    seq: MapReceiverSequence,
    mapper: &MapClosure,
    ctx: &SugarCtx,
) -> Result<MappedSequence, Outcome> {
    let floor = MapFloor::default();
    match seq {
        MapReceiverSequence::Values(seq) => {
            if let Some(values) = reduce_map_sequence_to_values(&seq, mapper) {
                trace_map_output_standing(&floor, values.len())?;
                tracing::debug!(
                    target: "sugar_lift_rust_tests::sugar::map",
                    len = values.len(),
                    "literal closure map reduced to value sequence"
                );
                return Ok(MappedSequence::Values(values));
            }
            match reduce_map_sequence_to_nested_values(&seq, mapper, ctx) {
                Ok(Some(values)) => {
                    trace_map_output_standing(&floor, values.len())?;
                    tracing::debug!(
                        target: "sugar_lift_rust_tests::sugar::map",
                        len = values.len(),
                        "literal closure map reduced to nested value sequence"
                    );
                    return Ok(MappedSequence::Values(values));
                }
                Ok(None) => {}
                Err(outcome) => return Err(outcome),
            }
            let operand = floor.derived_operand(seq.len())?;
            let out = floor.desugar(operand, seq, |idx, elem| {
                curry_map_body_for_elem(mapper, &elem, idx, ctx)
            })?;
            ctx.record_map_floor_audit(out.standing().count());
            trace_map_floor_output(out.standing());
            tracing::debug!(
                target: "sugar_lift_rust_tests::sugar::map",
                len = out.standing().count(),
                "literal closure map curried body terms"
            );
            Ok(MappedSequence::Terms(out.into_mapped()))
        }
        MapReceiverSequence::Terms(terms) => {
            let operand = floor.derived_operand(terms.len())?;
            let out = floor.desugar(operand, terms, |idx, term| {
                let label = canonical_term_sig(&term);
                curry_map_body_for_term(mapper, &term, idx, ctx, label)
            })?;
            ctx.record_map_floor_audit(out.standing().count());
            trace_map_floor_output(out.standing());
            tracing::debug!(
                target: "sugar_lift_rust_tests::sugar::map",
                len = out.standing().count(),
                "term sequence map curried body terms"
            );
            Ok(MappedSequence::Terms(out.into_mapped()))
        }
    }
}

fn trace_map_output_standing(floor: &MapFloor, count: usize) -> Result<(), Outcome> {
    let standing = floor
        .iter
        .alias(&MapOutputIterMember::new(count))
        .map_err(map_floor_refusal)?;
    trace_map_floor_output(&standing);
    Ok(())
}

fn trace_map_floor_output(standing: &IterStanding) {
    tracing::trace!(
        target: "sugar_lift_rust_tests::sugar::map",
        member = standing.member(),
        count = standing.count(),
        "map output stands on the iter floor"
    );
}

fn map_floor_refusal(err: TemporalFloorRefusal) -> Outcome {
    Outcome::Incomplete(Effect::CoverageGap {
        boundary: "Iterator::map".to_string(),
        reason: err.to_string(),
    })
}

fn reduce_map_sequence_to_values(
    seq: &[DesugaredElem],
    mapper: &MapClosure,
) -> Option<Vec<DesugaredElem>> {
    let mut out = Vec::with_capacity(seq.len());
    for elem in seq {
        let value = elem.value.as_ref()?;
        let mapped = if mapper.u128_shift_hint {
            const_eval_unary_closure_with_u128_shift(mapper.expr(), value)?
        } else {
            const_eval_unary_closure(mapper.expr(), value)?
        };
        let expr = mapped.to_expr()?;
        out.push(DesugaredElem {
            expr,
            value: Some(mapped),
        });
    }
    Some(out)
}

fn reduce_map_sequence_to_nested_values(
    seq: &[DesugaredElem],
    mapper: &MapClosure,
    ctx: &SugarCtx,
) -> Result<Option<Vec<DesugaredElem>>, Outcome> {
    let stable = stable_let_bindings(ctx.scope);
    let let_inits: BTreeMap<String, &Expr> = stable
        .iter()
        .map(|(name, init)| (name.clone(), init))
        .collect();
    let fcx = desugar_build_ctx(ctx.scope, ctx.options, &let_inits);
    let mut out = Vec::with_capacity(seq.len());
    for elem in seq {
        let Some(value) = elem.value.as_ref() else {
            return Ok(None);
        };
        let Some(body) = mapper.substituted_body_for(value) else {
            return Ok(None);
        };
        if !expr_is_literal_sequence_body(&body) {
            return Ok(None);
        }
        let Some(node) = method_family::build_literal_sequence_composite(&body, &fcx) else {
            return Ok(None);
        };
        let nested = match SugarBody::<CompositeFloor>::from_node(node).reduce(ctx) {
            Outcome::Complete(desugared) => desugared
                .into_seq()
                .unwrap_or_else(|| map_gap("map closure composite body reduced to non-sequence")),
            Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
        };
        let mut values = Vec::with_capacity(nested.len());
        for nested_elem in nested {
            let Some(value) = nested_elem.value else {
                return Ok(None);
            };
            values.push(value);
        }
        let value = ConstVal::Array(values);
        let expr = value
            .to_expr()
            .unwrap_or_else(|| map_gap("map nested sequence value did not reify to an expr"));
        out.push(DesugaredElem {
            expr,
            value: Some(value),
        });
    }
    Ok(Some(out))
}

fn curry_map_body_for_elem(
    mapper: &MapClosure,
    elem: &DesugaredElem,
    ordinal: usize,
    ctx: &SugarCtx,
) -> Result<Rc<Term>, Outcome> {
    let elem_term = sequence_elem_term_floor(elem, "map");
    curry_map_body_for_term(mapper, &elem_term, ordinal, ctx, token_key(&elem.expr))
}

fn curry_map_body_for_term(
    mapper: &MapClosure,
    elem_term: &Rc<Term>,
    ordinal: usize,
    ctx: &SugarCtx,
    elem_label: String,
) -> Result<Rc<Term>, Outcome> {
    let Some(binding) = &mapper.term_binding else {
        return Err(Outcome::Incomplete(Effect::CoverageGap {
            boundary: "Iterator::map".to_string(),
            reason: "map closure pattern is value-only; exact value reduction failed before a term floor could be built"
                .to_string(),
        }));
    };
    let curried_floor = match binding.body.reduce(ctx) {
        Outcome::Complete(d) => d.accept_desugared_floor(CurryVisitor {
            param: &binding.curry_param,
            arg: elem_term,
            occurrence: ctx.scope.temporal_curry_occurrence("map", ordinal),
        }),
        Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
    };
    let curried_floor = curried_floor.accept_desugared_floor(CurryVisitor {
        param: &binding.param,
        arg: elem_term,
        occurrence: ctx.scope.temporal_curry_occurrence("map", ordinal),
    });
    let curried = curried_floor
        .into_term()
        .unwrap_or_else(|| map_gap("map closure body reduced to non-Term floor"));
    tracing::trace!(
        target: "sugar_lift_rust_tests::sugar::map",
        elem = %elem_label,
        term = %canonical_term_sig(&curried),
        "map closure body curried through term dispatch"
    );
    Ok(curried)
}

fn closure_single_param_name(closure: &syn::ExprClosure) -> Option<String> {
    if closure.inputs.len() != 1 {
        return None;
    }
    pat_single_name(&closure.inputs[0])
}

fn pat_single_name(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(p) if p.subpat.is_none() => Some(p.ident.to_string()),
        Pat::Paren(paren) => pat_single_name(&paren.pat),
        Pat::Reference(reference) => pat_single_name(&reference.pat),
        Pat::Type(typed) => pat_single_name(&typed.pat),
        _ => None,
    }
}

fn closure_single_wildcard_literal_sequence(
    closure: &syn::ExprClosure,
    fcx: &SugarBuildCtx,
) -> bool {
    if closure.inputs.len() != 1 || !matches!(&closure.inputs[0], Pat::Wild(_)) {
        return false;
    }
    closure_tail_expr(closure).is_some_and(|tail| {
        expr_is_literal_sequence_body(tail)
            && method_family::build_literal_sequence_composite(tail, fcx).is_some()
    })
}

fn closure_tail_expr(closure: &syn::ExprClosure) -> Option<&Expr> {
    match closure.body.as_ref() {
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [syn::Stmt::Expr(expr, None)] => Some(expr),
            _ => None,
        },
        other => Some(other),
    }
}

fn expr_is_literal_sequence_body(expr: &Expr) -> bool {
    matches!(
        strip_refs_groups(expr),
        Expr::Array(_) | Expr::Range(_) | Expr::Repeat(_) | Expr::Macro(_)
    )
}

fn bind_expr_closure_arg(
    pat: &Pat,
    value: &ConstVal,
    bindings: &mut BTreeMap<String, Expr>,
) -> Option<()> {
    match pat {
        Pat::Ident(ident) if ident.subpat.is_none() => {
            bindings.insert(ident.ident.to_string(), value.to_expr()?);
            Some(())
        }
        Pat::Tuple(tuple) => {
            let ConstVal::Tuple(items) = value else {
                return None;
            };
            if tuple.elems.len() != items.len() {
                return None;
            }
            for (pat, item) in tuple.elems.iter().zip(items) {
                bind_expr_closure_arg(pat, item, bindings)?;
            }
            Some(())
        }
        Pat::Wild(_) => Some(()),
        Pat::Paren(paren) => bind_expr_closure_arg(&paren.pat, value, bindings),
        Pat::Reference(reference) => bind_expr_closure_arg(&reference.pat, value, bindings),
        Pat::Type(typed) => bind_expr_closure_arg(&typed.pat, value, bindings),
        _ => None,
    }
}

fn map_gap(reason: &str) -> ! {
    panic!("map completed without typed closure-body floors: {reason}")
}

pub(crate) fn receiver_has_unsigned_count_ones_range(expr: &Expr) -> bool {
    let Expr::Range(range) = strip_refs_groups(expr) else {
        return false;
    };
    range
        .end
        .as_deref()
        .is_some_and(expr_is_unsigned_count_ones)
}

fn expr_is_unsigned_count_ones(expr: &Expr) -> bool {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return false;
    };
    call.method == "count_ones" && expr_is_unsigned_assoc_const(&call.receiver)
}

fn expr_is_unsigned_assoc_const(expr: &Expr) -> bool {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return false;
    };
    if let Some(qself) = &path.qself {
        return type_is_unsigned_int(&qself.ty);
    }
    path.path
        .segments
        .first()
        .is_some_and(|segment| is_unsigned_int_name(&segment.ident.to_string()))
}

fn type_is_unsigned_int(ty: &Type) -> bool {
    let Type::Path(path) = ty else {
        return false;
    };
    path.path
        .segments
        .last()
        .is_some_and(|segment| is_unsigned_int_name(&segment.ident.to_string()))
}

fn is_unsigned_int_name(name: &str) -> bool {
    matches!(name, "u8" | "u16" | "u32" | "u64" | "u128" | "usize")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::temporal_floor::IterProvenance;

    #[test]
    fn map_floor_counts_real_map_output_as_iter_standing() {
        let floor = MapFloor::default();
        let operand = floor
            .derived_operand(3)
            .unwrap_or_else(|_| panic!("operand standing"));
        let output = floor
            .desugar(operand, [1, 2, 3], |idx, item| Ok(item + idx as i32))
            .unwrap_or_else(|_| panic!("map floor desugars"));

        assert_eq!(output.mapped, vec![1, 3, 5]);
        assert_eq!(output.standing().member(), "MapOutput");
        assert_eq!(output.standing().provenance(), IterProvenance::Derived);
        assert_eq!(output.standing().count(), 3);
    }

    #[test]
    fn map_floor_input_without_standing_refuses_loudly() {
        let err = IterStanding::new("MapInput", IterProvenance::Derived, None)
            .expect_err("missing operand standing refuses");
        let msg = err.to_string();

        assert!(msg.contains("crime=missing standing"));
        assert!(msg.contains("owner=IterFloor"));
        assert!(msg.contains("shape=MapInput carried no finite member count"));
        assert!(msg.contains("replacement=construct IterStanding"));
    }
}
