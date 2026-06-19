// SPDX-License-Identifier: Apache-2.0
//
// `BoundPathSugar`: a stable `let` binding used as a term is transparent to the
// ProofIR term it names. This is the general temporal-rewrite hook: consumers ask
// the factory for a child term, and a stable local such as `m` rewrites to the
// Sugar for `let m = Maker::new(42);` before `PathSugar` can freeze it as a bare
// variable.

use crate::sugar::bound::BoundSugar;
use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_constraint, build_term, SugarBuildCtx};
use crate::{token_key, Sugar};
use syn::{Expr, ExprPath};
use tracing::debug;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::secondary_term("bound_path", recognize);

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "bound_constraint",
    SugarRole::Constraint,
    SugarPriority::Primary,
    recognize_constraint,
);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let name = simple_local_path(expr)?;
    if fcx.resolving_bound_path(&name) {
        return None;
    }
    if let Some(current) = fcx.scope().temporal_rewrite_expr_for(&name) {
        debug!(
            target: "sugar_lift_rust_tests::temporal_rewrite",
            binding = name.as_str(),
            value = %token_key(&current),
            role = "Term",
            "temporal rewrite resolved path read"
        );
        let child_fcx = fcx.with_bound_path(&name);
        return Some(BoundSugar::new(name, build_term(&current, &child_fcx)));
    }
    let init = fcx.scope().stable_let_binding_for_term(&name)?;
    let child_fcx = fcx.with_bound_path(&name);
    Some(BoundSugar::new(name, build_term(init, &child_fcx)))
}

fn recognize_constraint(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let name = simple_local_path(expr)?;
    if fcx.resolving_bound_path(&name) {
        return None;
    }
    if let Some(current) = fcx.scope().temporal_rewrite_expr_for(&name) {
        debug!(
            target: "sugar_lift_rust_tests::temporal_rewrite",
            binding = name.as_str(),
            value = %token_key(&current),
            role = "Constraint",
            "temporal rewrite resolved path read"
        );
        let child_fcx = fcx.with_bound_path(&name);
        return Some(BoundSugar::new(
            name,
            build_constraint(&current, &child_fcx),
        ));
    }
    let init = fcx.scope().stable_let_binding_for_term(&name)?;
    let child_fcx = fcx.with_bound_path(&name);
    Some(BoundSugar::new(name, build_constraint(init, &child_fcx)))
}

fn simple_local_path(expr: &Expr) -> Option<String> {
    let Expr::Path(ExprPath {
        qself: None, path, ..
    }) = expr
    else {
        return None;
    };
    path.get_ident().map(ToString::to_string)
}
