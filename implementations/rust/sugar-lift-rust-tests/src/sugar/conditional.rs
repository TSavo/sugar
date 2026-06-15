// SPDX-License-Identifier: Apache-2.0
//
// ConditionalSugar -- the guarded-implication claim-side atom.
//
// Moved verbatim from lib.rs in the file-split refactor (one file per Sugar
// class). Behaviour-preserving: the desugar logic is byte-identical to the
// monolith; only its physical location changed.

use std::rc::Rc;

use sugar_ir_symbolic::Formula;
use syn::{Expr, Stmt};

use crate::*;

/// `ConditionalSugar`: the CLAIM-side atom (mirror of `LiteralSugar`, the
/// value-side atom). A guarded assertion `if <guard> { <then-asserts> }
/// [else { <else-asserts> }]` is the implication it literally states:
/// `guard => then` (and `not guard => else` when the else branch carries asserts).
///
/// SOUNDNESS LINE: we emit `guard => claim`, NEVER bare `claim`. Asserting the
/// body unconditionally when it is guarded would be a fake-discharge (the assert
/// only fires when the guard holds). `match` is nested conditionals; a bare
/// `assert!(P)` is the trivial `true => P` (handled by the normal unconditional
/// path, so `ConditionalSugar` engages only on the genuinely-guarded contexts the
/// trunk previously refused).
///
/// EXACT-OR-BAIL: the guard must translate to a Formula via the SAME path an
/// `assert!(guard)` would take (`translate_bool_assertion`); the then/else asserts
/// must lift all-or-nothing through the normal collector; the guard / body must be
/// pure (no mutation / iterator-advance -- a side-effecting branch is not a
/// timeless point-wise claim). Any miss -> None (bail; the existing if-context
/// refusal stands).
pub(crate) struct ConditionalSugar {
    pub(crate) cond: Expr,
    pub(crate) then_stmts: Vec<Stmt>,
    pub(crate) else_stmts: Vec<Stmt>,
}

impl Sugar for ConditionalSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Option<Desugared> {
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
        // The guard formula -- lifted EXACTLY as `assert!(guard)` would lift it. A
        // guard outside the liftable predicate set (an opaque method call, a float
        // refinement we cannot width, ...) -> bail.
        let guard = lower_assert_condition(&self.cond, ctx.scope, &ctx.float_widths.borrow())
            .ok()?
            .atom;

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
            ctx.macro_depth,
            &ctx.scope.plan.interior_mut,
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
