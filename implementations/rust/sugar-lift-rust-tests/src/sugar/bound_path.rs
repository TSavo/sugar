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
use crate::sugar::term_leaf::{reasoned_hit, resolved_term};
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
    if let Some(hit) = alias_deref_mutated_refusal(&name, fcx) {
        return Some(hit);
    }
    if let Some(hit) = loop_body_mutated_refusal(&name, fcx) {
        return Some(hit);
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
    if let Some(term) = fcx.scope().stable_term_binding_for_term(&name) {
        debug!(
            target: "sugar_lift_rust_tests::bound_path",
            binding = name.as_str(),
            role = "Term",
            "resolved path read through term binding"
        );
        return Some(BoundSugar::new(name, resolved_term(term)));
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
    if let Some(hit) = alias_deref_mutated_refusal(&name, fcx) {
        return Some(hit);
    }
    if let Some(hit) = loop_body_mutated_refusal(&name, fcx) {
        return Some(hit);
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

/// THE NO-FALSE-REFUTATION GATE. A local MUTATED through a `&mut` alias the tracker
/// cannot resolve (`let r = &mut x; *r += 1;`) has a STALE tracked value -- the
/// alias-deref mutation is refused, so the rewrite never applies it. Reading that local
/// would lift the pre-mutation literal (`assert_eq!(x, 6)` -> `5 == 6`, UNSAT), which
/// REFUTES a true assertion: the inverse cardinal sin (a fake dragon over correct code).
/// So such a read REFUSES by name instead of resolving. This is conservative refuse-
/// tightening (it never adds a warrant, so it cannot false-DISCHARGE) and it makes the
/// no-false-refutation an EXPLICIT, intentional refuse rather than a coincidental
/// co-refusal masking. It does NOT warrant the post-mutation value -- that is the
/// attended SSA arm's job; this only stops the stale read.
fn alias_deref_mutated_refusal(name: &str, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    fcx.scope().is_alias_deref_mutated(name).then(|| {
        // Classified as `ambiguous temporal identity` (the terminal-today Refused bucket
        // for an aliased-mutated value with no single `t`) -- the SAME family as a
        // conditionally/aliased-mutated receiver. Per the boundary-call note on that
        // reason, it flips to a warrant once the attended SSA arm teaches alias-mutation
        // resolution; until then it is a NAMED dragon, not a stale fake-light.
        reasoned_hit(format!(
            "ambiguous temporal identity for `{name}`: mutated through a `&mut` alias \
             between borrow and read, so there is no single timeless value to read at the \
             assertion; refused"
        ))
    })
}

/// THE LOOP-BODY TEMPORAL-INSTABILITY GATE. A mut-local mutated INSIDE a loop body
/// (`for`/`while`/`loop`) has a STALE tracked value after the loop -- the syntactic
/// tracker cannot propagate the loop's net effect, so the pre-loop literal persists.
/// A post-loop read resolves to that stale value, lifting e.g. `0 == 3` (UNSAT) which
/// REFUTES a true assertion: the inverse cardinal sin (a fake dragon over correct code).
/// Also covers mut-iterators consumed via `.next()`/`.by_ref()` inside a loop whose
/// post-loop `.len()` EUF-collapses to the initial (pre-consumption) value.
///
/// Reads of such locals REFUSE by name (→ UNDECIDED, not REFUTED). Conservative
/// refuse-tightening: zero new warrant, zero false-discharge risk.
fn loop_body_mutated_refusal(name: &str, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    fcx.scope().is_loop_body_mutated(name).then(|| {
        reasoned_hit(format!(
            "temporally unstable post-loop read of `{name}`: mutated inside a loop body \
             so the post-loop value is not tracked; refused as temporally unstable"
        ))
    })
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
