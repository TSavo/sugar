// SPDX-License-Identifier: Apache-2.0
//
// `MapSugar`: the `.map(f)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that replaces each element with the closure's const value. Bails
// (None) on an opaque element (no const value), a runtime/overflowing closure, or a
// mapped value it cannot materialize back to an `Expr`. Lifted verbatim from the
// `Adaptor::Map(closure)` arm of the former `apply_one_adaptor` match.

use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};
use syn::{Expr, Pat, Type};

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::method_family;
use crate::sugar::term_dispatch::{CurryOccurrence, CurryVisitor, DesugaredFloorAccept};
use crate::{
    canonical_term_sig, closure_body_mutates_captured_runtime_state, const_eval_unary_closure,
    const_val_term, curry_param_name, curry_param_term, strip_refs_groups, token_key, Desugared,
    DesugaredElem, Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("map", recognize_composite);
pub(crate) const TERM_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("map_term", recognize_term);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
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
            receiver_is_u128_count_ones_range(&call.receiver),
        )?,
    }))
}

pub(crate) fn recognize_term(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
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
            receiver_is_u128_count_ones_range(&call.receiver),
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
        let param = closure_single_param_name(&expr)?;
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
                        .and_then(const_val_term)
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
        let mapped = const_eval_unary_closure(mapper.expr(), value)?;
        let expr = mapped.to_expr()?;
        out.push(DesugaredElem {
            expr,
            value: Some(mapped),
        });
    }
    Some(out)
}

fn curry_map_body_for_elem(
    mapper: &MapClosure,
    elem: &DesugaredElem,
    ordinal: usize,
    ctx: &SugarCtx,
) -> Result<Rc<Term>, Outcome> {
    let elem_term = elem_term_floor(elem);
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

fn elem_term_floor(elem: &DesugaredElem) -> Rc<Term> {
    elem.value
        .as_ref()
        .and_then(const_val_term)
        .unwrap_or_else(|| make_var(format!("opaque:map-elem:{}", token_key(&elem.expr))))
}

fn map_gap(reason: &str) -> ! {
    panic!("map completed without typed closure-body floors: {reason}")
}

fn receiver_is_u128_count_ones_range(expr: &Expr) -> bool {
    let Expr::Range(range) = strip_refs_groups(expr) else {
        return false;
    };
    range.end.as_deref().is_some_and(expr_is_u128_count_ones)
}

fn expr_is_u128_count_ones(expr: &Expr) -> bool {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return false;
    };
    call.method == "count_ones" && expr_is_u128_assoc_const(&call.receiver)
}

fn expr_is_u128_assoc_const(expr: &Expr) -> bool {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return false;
    };
    if let Some(qself) = &path.qself {
        return type_is_u128(&qself.ty);
    }
    path.path
        .segments
        .first()
        .is_some_and(|segment| segment.ident == "u128")
}

fn type_is_u128(ty: &Type) -> bool {
    let Type::Path(path) = ty else {
        return false;
    };
    path.path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == "u128")
}
