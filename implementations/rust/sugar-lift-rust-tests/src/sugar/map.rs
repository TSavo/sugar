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
use crate::sugar::term_dispatch::{CurryOccurrence, CurryVisitor, DesugaredFloorAccept};
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
        crate::sugar::claim::SugarWitnesses::Pending,
        recognize_composite,
    );
pub(crate) const TERM_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "map_term",
        crate::sugar::claim::SugarWitnesses::Pending,
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
    curry_param: String,
    body: SugarBody<TermFloor>,
    u128_shift_hint: bool,
}

impl MapClosure {
    pub(crate) fn build(
        expr: syn::ExprClosure,
        fcx: &SugarBuildCtx,
        u128_shift_hint: bool,
    ) -> Option<Self> {
        let param = closure_single_param_name(&expr).or_else(|| {
            closure_single_wildcard_literal_sequence(&expr, fcx).then(|| "_".to_string())
        })?;
        let curry_param = curry_param_name(&param);
        let body_scope = fcx
            .scope()
            .fork_with_stable_term_binding(&param, curry_param_term(&param));
        let body_fcx = fcx.with_scope(&body_scope);
        let body = SugarBody::<TermFloor>::term(expr.body.as_ref(), &body_fcx);
        Some(Self {
            expr,
            curry_param,
            body,
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
    match seq {
        MapReceiverSequence::Values(seq) => {
            if let Some(values) = reduce_map_sequence_to_values(&seq, mapper) {
                tracing::debug!(
                    target: "sugar_lift_rust_tests::sugar::map",
                    len = values.len(),
                    "literal closure map reduced to value sequence"
                );
                return Ok(MappedSequence::Values(values));
            }
            match reduce_map_sequence_to_nested_values(&seq, mapper, ctx) {
                Ok(Some(values)) => {
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
            let mut out = Vec::with_capacity(seq.len());
            for (idx, elem) in seq.into_iter().enumerate() {
                out.push(curry_map_body_for_elem(mapper, &elem, idx, ctx)?);
            }
            tracing::debug!(
                target: "sugar_lift_rust_tests::sugar::map",
                len = out.len(),
                "literal closure map curried body terms"
            );
            Ok(MappedSequence::Terms(out))
        }
        MapReceiverSequence::Terms(terms) => {
            let mut out = Vec::with_capacity(terms.len());
            for (idx, term) in terms.into_iter().enumerate() {
                out.push(curry_map_body_for_term(
                    mapper,
                    &term,
                    idx,
                    ctx,
                    canonical_term_sig(&term),
                )?);
            }
            tracing::debug!(
                target: "sugar_lift_rust_tests::sugar::map",
                len = out.len(),
                "term sequence map curried body terms"
            );
            Ok(MappedSequence::Terms(out))
        }
    }
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
    let curried_floor = match mapper.body.reduce(ctx) {
        Outcome::Complete(d) => d.accept_desugared_floor(CurryVisitor {
            param: &mapper.curry_param,
            arg: elem_term,
            occurrence: CurryOccurrence {
                family: "map",
                ordinal,
            },
        }),
        Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
    };
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
