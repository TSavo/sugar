// SPDX-License-Identifier: Apache-2.0

use std::{collections::BTreeMap, rc::Rc};

use sugar_ir_symbolic::{make_var, Term};
use syn::{Expr, Pat};

use crate::sugar::factory::{BoolFloor, SugarBody, SugarBuildCtx};
use crate::sugar::term_dispatch::{
    literal_predicate_bool_or_runtime_effect, CurryVisitor, DesugaredFloorAccept,
};
use crate::{
    canonical_term_sig, const_val_term, curry_param_name, curry_param_term, helper_param_names,
    simple_path_name, strip_refs_groups, token_key, value_body_tail_substituted, DesugaredElem,
    Outcome, SugarCtx,
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
                occurrence: ctx.scope.temporal_curry_occurrence(family, ordinal),
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
/// The factory resolves its body once, pins it as a bool floor, and desugar only
/// curries each sequence element's term through that floor.
pub(crate) struct BoolPredicateFunction {
    body: BoolPredicateFunctionBody,
}

struct BoolPredicateFunctionBody {
    curry_param: String,
    body: SugarBody<BoolFloor>,
}

impl BoolPredicateFunction {
    pub(crate) fn build_result(expr: Expr, fcx: &SugarBuildCtx) -> Result<Self, String> {
        let name = simple_path_name(strip_refs_groups(&expr)).ok_or_else(|| {
            format!(
                "predicate `{}` is not a simple visible fn path",
                crate::token_key(&expr)
            )
        })?;
        if !fcx.scope().has_visible_fn(&name) {
            return Err(format!(
                "predicate `{name}` is not visible in the current temporal scope"
            ));
        }
        BoolPredicateFunctionBody::build_result(expr, fcx).map(|body| Self { body })
    }

    pub(crate) fn eval_for_elem(
        &self,
        elem: &DesugaredElem,
        ordinal: usize,
        family: &'static str,
        ctx: &SugarCtx,
    ) -> Result<bool, Outcome> {
        let elem_term = elem_term_floor(elem, family);
        let body = match self.body.body.reduce(ctx) {
            Outcome::Complete(d) => d.accept_desugared_floor(CurryVisitor {
                param: &self.body.curry_param,
                arg: &elem_term,
                occurrence: ctx.scope.temporal_curry_occurrence(family, ordinal),
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
                    "function predicate floor did not reduce to literal bool: {}",
                    canonical_term_sig(&term)
                ),
            ),
        }
    }
}

impl BoolPredicateFunctionBody {
    fn build_result(func: Expr, fcx: &SugarBuildCtx) -> Result<Self, String> {
        let name = simple_path_name(strip_refs_groups(&func)).ok_or_else(|| {
            format!(
                "predicate `{}` is not a simple visible fn path",
                crate::token_key(&func)
            )
        })?;
        let helper = fcx.scope().visible_fn(&name).ok_or_else(|| {
            format!("predicate `{name}` is not visible in the current temporal scope")
        })?;
        if helper.sig.asyncness.is_some() {
            return Err(format!("predicate `{name}` is async"));
        }
        if crate::count_asserts_in_stmts(&helper.block.stmts) != 0 {
            return Err(format!("predicate `{name}` contains assertions"));
        }
        let params = helper_param_names(&helper).map_err(|reason| {
            format!("predicate `{name}` parameter list is not curryable: {reason}")
        })?;
        let [param] = params.as_slice() else {
            return Err(format!(
                "predicate `{name}` has {} parameters, expected exactly one",
                params.len()
            ));
        };
        let curry_param = curry_param_name(param);
        let body_scope = fcx
            .scope()
            .fork_with_stable_term_binding(param, curry_param_term(param));
        let body_fcx = fcx.with_scope(&body_scope);
        let mut bindings = BTreeMap::new();
        let returned = value_body_tail_substituted(&helper.block, &mut bindings)
            .ok_or_else(|| format!("predicate `{name}` does not have a pure value tail"))?;
        Ok(Self {
            curry_param,
            body: SugarBody::<BoolFloor>::bool_expr(&returned, &body_fcx),
        })
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
