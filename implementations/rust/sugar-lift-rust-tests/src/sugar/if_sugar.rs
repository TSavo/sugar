// SPDX-License-Identifier: Apache-2.0
//
// IfSugar: lifts `if COND { THEN } [else { ELSE }]` (and `else if ...` chains)
// to `Desugared::StmtBlock { guarded, fall_through }`.
//
// Recognized shape: `Stmt::Expr(Expr::If(..), _)` (with or without trailing semi).
//
// Semantics (mirror of Python IfSugar):
//   - The condition is lifted as a Formula via `assertion_entry_with_audits`, with
//     `eq(term, bool_const(true))` as a term-level fallback.
//   - The then-branch (always a `syn::Block`) is wrapped as a synthetic
//     `Stmt::Expr(Expr::Block(..), None)` and dispatched to BlockSugar via
//     `build_stmt_role`. BlockSugar produces `StmtBlock { guarded, fall_through }`.
//   - Guards from the then-branch each get `cond` prepended.
//   - No else: `fall_through = [not_(cond)]`. The outer BlockSugar will prepend
//     this as a guard for any subsequent statements (they run only when cond is false).
//   - With else: the else-branch (`Expr::Block` or `Expr::If` for else-if chains) is
//     dispatched similarly; its guards get `not_(cond)` prepended; `fall_through = []`
//     (the else clause is exhaustive).
//
// Nested `else if` chains recurse naturally: the else expression is an `Expr::If`,
// which becomes `Stmt::Expr(Expr::If(..), None)` -> IfSugar again.
//
// LAW: no hand-rolled Formula/post construction. Condition lifting uses the constraint
// factory; branch reduction uses `build_stmt_role` -> BlockSugar.

use std::rc::Rc;

use sugar_ir_symbolic::{eq, not_, Formula};
use syn::{Expr, ExprIf, Stmt};

use crate::sugar::catalog::build_stmt_role;
use crate::sugar::claim::{StmtSugarClaim, SugarRole};
use crate::sugar::constraint::assertion_entry_with_audits;
use crate::sugar::control_flow_guard_operation::guard_block;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::guarded_return::GuardedReturn;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_dispatch::translate_term_in_scope;
use crate::{bool_const, Desugared, Effect, FloatWidthScope, Outcome, Sugar, SugarCtx};

pub(crate) static STMT_SUGAR: StmtSugarClaim = StmtSugarClaim::statement("if_sugar", recognize);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let stmt = frag.as_stmt()?;
    let Stmt::Expr(Expr::If(if_expr), _) = stmt else {
        return None;
    };
    let then_stmt = Stmt::Expr(
        Expr::Block(syn::ExprBlock {
            attrs: vec![],
            label: None,
            block: if_expr.then_branch.clone(),
        }),
        None,
    );
    let then_node = build_stmt_role(&then_stmt, fcx, SugarRole::Statement);
    let else_node = if_expr.else_branch.as_ref().map(|(_, else_expr)| {
        let else_stmt = Stmt::Expr(*else_expr.clone(), None);
        build_stmt_role(&else_stmt, fcx, SugarRole::Statement)
    });
    Some(Box::new(IfSugar {
        if_expr: if_expr.clone(),
        then_node,
        else_node,
    }))
}

struct IfSugar {
    if_expr: ExprIf,
    then_node: Box<dyn Sugar>,
    else_node: Option<Box<dyn Sugar>>,
}

impl Sugar for IfSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        // Lift condition as a Formula. The assertion_entry_with_audits path handles
        // comparisons, boolean ops, and matches!. On failure we fall back to a raw
        // term and wrap it as eq(t, true).
        let cond_formula: Rc<Formula> = match assertion_entry_with_audits(
            &self.if_expr.cond,
            ctx.scope,
            &FloatWidthScope::new(),
            ctx.factory_audits,
        ) {
            Ok(entry) => entry.atom,
            Err(_) => match translate_term_in_scope(&self.if_expr.cond, ctx.scope) {
                Ok(t) => eq(t, bool_const(true)),
                Err(effect) => return Outcome::Incomplete(effect),
            },
        };
        let not_cond = not_(cond_formula.clone());

        let (then_guarded, then_fall) = match reduce_branch(self.then_node.as_ref(), ctx, "then") {
            Ok(branch) => branch,
            Err(effect) => return Outcome::Incomplete(effect),
        };

        // Prepend `cond` to every guard clause from the then-branch.
        let (mut all_guarded, _then_fall) =
            guard_block(then_guarded, then_fall, &[cond_formula.clone()], "IfSugar");

        match &self.if_expr.else_branch {
            None => {
                // No else: fall_through captures the "cond was false" condition.
                // The outer BlockSugar uses this as a guard for subsequent statements.
                Outcome::Complete(Desugared::StmtBlock {
                    guarded: all_guarded,
                    fall_through: vec![not_cond],
                })
            }
            Some(_) => {
                // The else expression is Expr::Block (plain `else { ... }`) or
                // Expr::If (an `else if ...` chain). Both are dispatched via build_stmt_role.
                let Some(else_node) = self.else_node.as_ref() else {
                    panic!("if_sugar: else expression had no constructed branch node");
                };
                let (else_guarded, _else_fall) =
                    match reduce_branch(else_node.as_ref(), ctx, "else") {
                        Ok(branch) => branch,
                        Err(effect) => return Outcome::Incomplete(effect),
                    };

                let (else_guarded, _else_fall) =
                    guard_block(else_guarded, _else_fall, &[not_cond.clone()], "IfSugar");
                all_guarded.extend(else_guarded);

                // With an else branch the alternatives are exhaustive: no fall_through.
                Outcome::Complete(Desugared::StmtBlock {
                    guarded: all_guarded,
                    fall_through: vec![],
                })
            }
        }
    }
}

fn reduce_branch(
    node: &dyn Sugar,
    ctx: &SugarCtx,
    branch: &'static str,
) -> Result<(Vec<GuardedReturn>, Vec<Rc<Formula>>), Effect> {
    match node.reduce(ctx) {
        Outcome::Complete(Desugared::StmtBlock {
            guarded,
            fall_through,
        }) => Ok((guarded, fall_through)),
        Outcome::Incomplete(effect) => Err(effect),
        _ => panic!("if_sugar: {branch}-branch did not reduce to StmtBlock"),
    }
}
