// SPDX-License-Identifier: Apache-2.0
//
// `ConditionalSugar`: a guarded point-wise claim (`if cond { asserts } else { asserts }`)
// reduced to `cond => then-conj` and `!cond => else-conj`. Relocated verbatim from the
// `lib.rs` monolith (pure code-motion, zero behavior change). Carries its OWNED
// `decompose_if` constructor. Shared substrate (the collector, the bool-assertion
// translator, `const_fold_bool_guard`, the purity gates) stays in `crate::`.

use std::collections::{BTreeMap, HashSet};
use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, implies, not_, Formula};
use syn::{Expr, Stmt};

use crate::sugar::backstop::boxed;
use crate::sugar::factory::SugarBuildCtx;
use crate::{
    bool_const, closure_body_is_side_effecting, collect_assertion_entries, const_fold_bool_guard,
    count_asserts_in_stmts, loop_body_mutates, lower_assert_condition, Desugared, Outcome, Sugar,
    SugarCtx, Warrant,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("conditional", recognize_composite);

/// COMPOSITE recognizer for `Expr::If`: the implication composite ([`ConditionalSugar`]
/// via [`decompose_if`]). Byte-identical to the `Expr::If(i) => boxed(decompose_if(i))`
/// arm of the old fat `build_composite`.
pub(crate) fn recognize_composite(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::If(i) => Some(boxed(decompose_if(i))),
        _ => None,
    }
}

/// EXACT-OR-BAIL: the guard must translate to a Formula via the SAME path an
/// `assert!(guard)` would take (`translate_bool_assertion`); the then/else asserts
/// must lift all-or-nothing through the normal collector; the guard / body must be
/// pure (no mutation / iterator-advance -- a side-effecting branch is not a
/// timeless point-wise claim). Any miss -> None (bail; the existing if-context
/// refusal stands).
pub(crate) struct ConditionalSugar {
    cond: Expr,
    then_stmts: Vec<Stmt>,
    else_stmts: Vec<Stmt>,
}

impl Sugar for ConditionalSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        // TOTAL: the dig body computes the legacy `Option<Desugared>`; `Outcome::from_opt`
        // lifts it (the structural bail -> `Hit(Effect::Unsupported)`, discarded by the
        // fall-through consumer exactly as the old `None` was).
        Outcome::from_opt((|| {
            // An `if let PAT = e { .. }` is a pattern-match guard, not a boolean
            // predicate -- the panic-locus path handles the diverging-else shape;
            // anything else here bails (we do not model the bound bindings).
            if matches!(&self.cond, Expr::Let(_)) {
                return None;
            }
            // The guard must not mutate / advance state (a side-effecting condition is
            // not a timeless predicate). Reuse the verified closure-body scanner over
            // the condition expression.
            if closure_body_is_side_effecting(&self.cond) {
                return None;
            }
            let then_count = count_asserts_in_stmts(&self.then_stmts);
            let else_count = count_asserts_in_stmts(&self.else_stmts);
            // At least one branch must carry an assertion (else nothing to classify --
            // leave it to the existing handling).
            if then_count + else_count == 0 {
                return None;
            }
            // Neither branch may mutate captured state: a single guarded implication is
            // a point-wise claim only if the branch body is pure.
            if loop_body_mutates(&self.then_stmts) || loop_body_mutates(&self.else_stmts) {
                return None;
            }
            // The guard formula. FIRST try const-folding a compile-time-constant guard
            // (`!false` -> true, `!true` -> false, `cfg!(target_pointer_width=..)` ->
            // the resolved cfg bool): such a guard's truth is fixed from the source, so
            // it lifts as a CONSTANT antecedent `<folded> == true`. The emitted
            // `guard_const => P` is faithful -- a true guard forces P, a false guard makes
            // the implication trivially hold (the body never runs). This drains the
            // const/cfg if-guard bucket (corpus: bool.rs / step.rs / fmt/mod.rs) the
            // expression-predicate path below cannot reach (a bare bool literal / `cfg!`
            // is not a translatable comparison). Otherwise fall back to lifting the guard
            // EXACTLY as `assert!(guard)` would; a guard outside the liftable predicate
            // set (an opaque method call, a float refinement we cannot width, ...) bails.
            let guard = match const_fold_bool_guard(&self.cond, ctx.options) {
                Some(value) => eq(bool_const(value), bool_const(true)),
                None => {
                    lower_assert_condition(
                        &self.cond,
                        ctx.scope,
                        &ctx.float_widths.borrow(),
                        ctx.factory_audits,
                    )
                    .ok()?
                    .atom
                }
            };

            let mut conjuncts: Vec<Rc<Formula>> = Vec::new();
            if then_count > 0 {
                let then_conj = self.lift_branch_conj(&self.then_stmts, then_count, ctx)?;
                // guard => then.
                conjuncts.push(implies(guard.clone(), then_conj));
            }
            if else_count > 0 {
                let else_conj = self.lift_branch_conj(&self.else_stmts, else_count, ctx)?;
                // not guard => else (the else branch fires when the guard is false).
                conjuncts.push(implies(not_(guard.clone()), else_conj));
            }
            let atom = and_(conjuncts);
            let warrant = Warrant {
                name: Some(format!("{}::if", ctx.scope.local_scope())),
            };
            Some(Desugared::Constraints {
                atom,
                n: then_count + else_count,
                warrant,
            })
        })())
    }
}

impl ConditionalSugar {
    /// Lift a branch's statements all-or-nothing through the normal collector,
    /// returning the conjunction of its assert atoms or None (bail) if any branch
    /// assert refuses / is missing (truth-table-or-gutter, mirroring
    /// `lift_bounded_forall`'s body lift).
    fn lift_branch_conj(
        &self,
        branch_stmts: &[Stmt],
        expected: usize,
        ctx: &SugarCtx,
    ) -> Option<Rc<Formula>> {
        let mut body_entries = Vec::new();
        let mut body_skipped = Vec::new();
        let mut body_lifted = 0usize;
        let mut body_helpers = HashSet::new();
        collect_assertion_entries(
            branch_stmts,
            ctx.scope.local_scope(),
            ctx.options,
            ctx.reducer,
            *ctx.float_widths.borrow_mut(),
            &mut body_entries,
            &mut body_skipped,
            &mut body_lifted,
            &mut body_helpers,
            ctx.factory_audits,
            ctx.macro_depth,
            &ctx.scope.plan.interior_mut,
            &BTreeMap::new(),
        );
        if !body_skipped.is_empty() || body_entries.len() != expected {
            return None;
        }
        Some(and_(body_entries.iter().map(|e| e.atom.clone()).collect()))
    }
}

/// Build a `ConditionalSugar` from a `Stmt::Expr(Expr::If(..))`. The then-branch
/// statements and the else-branch statements (a plain `else { .. }` block; an
/// `else if` chains as a nested `Expr::If`, captured as the single else statement)
/// are the guarded claims. None if the if has no body to classify.
pub(crate) fn decompose_if(i: &syn::ExprIf) -> Option<ConditionalSugar> {
    let else_stmts: Vec<Stmt> = match &i.else_branch {
        Some((_, else_expr)) => match &**else_expr {
            Expr::Block(b) => b.block.stmts.clone(),
            // `else if ..` / any other else expr: keep as one statement so its
            // asserts are counted and lifted (a nested ConditionalSugar reached via
            // the recursive collector). A non-block else with asserts that does not
            // fully lift will make the branch lift bail -- honest.
            other => vec![Stmt::Expr(other.clone(), None)],
        },
        None => Vec::new(),
    };
    Some(ConditionalSugar {
        cond: (*i.cond).clone(),
        then_stmts: i.then_branch.stmts.clone(),
        else_stmts,
    })
}
