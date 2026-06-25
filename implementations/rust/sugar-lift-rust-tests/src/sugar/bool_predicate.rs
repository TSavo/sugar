// SPDX-License-Identifier: Apache-2.0

use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};
use syn::{Expr, Pat};

use crate::sugar::factory::{BoolFloor, SugarBody, SugarBuildCtx};
use crate::sugar::term_dispatch::{
    literal_predicate_bool_or_runtime_effect, CurryOccurrence, CurryVisitor, DesugaredFloorAccept,
};
use crate::{
    canonical_term_sig, const_val_term, simple_path_name, strip_refs_groups, token_key,
    DesugaredElem, Outcome, SugarCtx,
};

/// A unary predicate closure whose body is already factory-owned.
///
/// Sequence adaptors (`filter`, `skip_while`, `take_while`) do not evaluate closure
/// syntax themselves. They curry the completed body floor with each element and ask the
/// result to dispatch as a bool literal.
pub(crate) struct BoolPredicateClosure {
    param: String,
    body: SugarBody<BoolFloor>,
}

impl BoolPredicateClosure {
    pub(crate) fn build(expr: syn::ExprClosure, fcx: &SugarBuildCtx) -> Option<Self> {
        Some(Self {
            param: closure_single_param_name(&expr)?,
            body: SugarBody::<BoolFloor>::bool_expr(expr.body.as_ref(), fcx),
        })
    }

    pub(crate) fn eval_for_elem(
        &self,
        elem: &DesugaredElem,
        ordinal: usize,
        family: &'static str,
        ctx: &SugarCtx,
    ) -> Result<bool, Outcome> {
        let elem_term = elem_term_floor(elem, family);
        let body = match self.body.reduce(ctx) {
            Outcome::Complete(d) => d.accept_desugared_floor(CurryVisitor {
                param: &self.param,
                arg: &elem_term,
                occurrence: CurryOccurrence { family, ordinal },
            }),
            Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
        };
        let term = body
            .into_term()
            .unwrap_or_else(|| bool_predicate_gap(family, "predicate body reduced to non-Term"));
        match literal_predicate_bool_or_runtime_effect(&term) {
            Ok(Some(value)) => Ok(value),
            Err(effect) => Err(Outcome::Incomplete(effect)),
            Ok(None) => bool_predicate_gap(
                family,
                &format!(
                    "predicate floor did not reduce to literal bool: {}",
                    canonical_term_sig(&term)
                ),
            ),
        }
    }
}

/// A visible source function used as an iterator predicate (`.skip_while(p)`).
/// The function body is resolved at desugar time with the concrete element value and
/// then dispatched through the same bool-literal visitor as closure predicates.
pub(crate) struct BoolPredicateFunction {
    func: Expr,
}

impl BoolPredicateFunction {
    pub(crate) fn build(expr: Expr, _fcx: &SugarBuildCtx) -> Option<Self> {
        simple_path_name(strip_refs_groups(&expr))?;
        Some(Self { func: expr })
    }

    pub(crate) fn eval_for_elem(
        &self,
        elem: &DesugaredElem,
        _ordinal: usize,
        family: &'static str,
        ctx: &SugarCtx,
    ) -> Result<bool, Outcome> {
        let value = elem
            .value
            .as_ref()
            .unwrap_or_else(|| bool_predicate_gap(family, "function predicate element was opaque"));
        let arg = value.to_expr().unwrap_or_else(|| {
            bool_predicate_gap(family, "function predicate element could not materialize")
        });
        let term = match ctx.try_inline_value_call(&self.func, &[arg]) {
            Ok(Some(term)) => term,
            Ok(None) => bool_predicate_gap(
                family,
                "function predicate body did not reduce to a bool floor",
            ),
            Err(effect) => return Err(Outcome::Incomplete(effect)),
        };
        match literal_predicate_bool_or_runtime_effect(&term) {
            Ok(Some(value)) => Ok(value),
            Err(effect) => Err(Outcome::Incomplete(effect)),
            Ok(None) => bool_predicate_gap(
                family,
                &format!(
                    "function predicate floor did not reduce to literal bool: {}",
                    canonical_term_sig(&term)
                ),
            ),
        }
    }
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

fn elem_term_floor(elem: &DesugaredElem, family: &str) -> Rc<Term> {
    elem.value
        .as_ref()
        .and_then(const_val_term)
        .unwrap_or_else(|| make_var(format!("opaque:{family}-elem:{}", token_key(&elem.expr))))
}

fn bool_predicate_gap(owner: &str, reason: &str) -> ! {
    panic!("{owner} predicate did not reach a lawful bool floor: {reason}")
}
