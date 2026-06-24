// SPDX-License-Identifier: Apache-2.0

use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};
use syn::{Expr, Pat};

use crate::sugar::factory::{BoolFloor, SugarBody, SugarBuildCtx};
use crate::sugar::term_dispatch::{
    BoolFloorAccept, CurryOccurrence, CurryVisitor, DesugaredFloorAccept, RequiredBoolVisitor,
};
use crate::{const_val_term, token_key, DesugaredElem, Outcome, SugarCtx};

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
        Ok(term.accept_bool_floor(RequiredBoolVisitor { owner: family }))
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
