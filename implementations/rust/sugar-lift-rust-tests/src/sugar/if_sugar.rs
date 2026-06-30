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

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{eq, not_, Formula, Term};
use syn::{Expr, ExprIf, Item, Stmt};

use crate::sugar::catalog::build_stmt_role;
use crate::sugar::claim::{StmtSugarClaim, SugarRole};
use crate::sugar::constraint::assertion_entry_with_audits;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_dispatch::translate_term_in_scope;
use crate::{
    bool_const, sugar_ctx_with_factory_audits, Desugared, FloatWidthScope, LiftOptions, Outcome,
    ReductionCtx, Sugar, SugarCtx,
};

pub(crate) static STMT_SUGAR: StmtSugarClaim = StmtSugarClaim::statement("if_sugar", recognize);

fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let stmt = frag.as_stmt()?;
    let Stmt::Expr(Expr::If(if_expr), _) = stmt else {
        return None;
    };
    Some(Box::new(IfSugar {
        if_expr: if_expr.clone(),
    }))
}

struct IfSugar {
    if_expr: ExprIf,
}

impl Sugar for IfSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();

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

        // Reduce then-branch as a BlockSugar via build_stmt_role.
        let then_stmt = Stmt::Expr(
            Expr::Block(syn::ExprBlock {
                attrs: vec![],
                label: None,
                block: self.if_expr.then_branch.clone(),
            }),
            None,
        );
        let (then_guarded, _then_fall) = {
            let items: Vec<Item> = Vec::new();
            let fcx = SugarBuildCtx::new(ctx.scope, &options, &let_inits);
            let then_node = build_stmt_role(&then_stmt, &fcx, SugarRole::Statement);
            let reducer = ReductionCtx::from_items_with_imports(&items, ctx.scope.macro_registry());
            let mut fw = FloatWidthScope::new();
            let child_ctx = sugar_ctx_with_factory_audits(
                ctx.scope,
                &options,
                &reducer,
                &mut fw,
                0,
                ctx.factory_audits,
            );
            match then_node.reduce(&child_ctx) {
                Outcome::Complete(Desugared::StmtBlock {
                    guarded,
                    fall_through,
                }) => (guarded, fall_through),
                Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
                _ => panic!("if_sugar: then-branch did not reduce to StmtBlock"),
            }
        };

        // Prepend `cond` to every guard clause from the then-branch.
        let mut all_guarded: Vec<(Vec<Rc<Formula>>, Rc<Term>)> = then_guarded
            .into_iter()
            .map(|(mut guards, term)| {
                guards.insert(0, cond_formula.clone());
                (guards, term)
            })
            .collect();

        match &self.if_expr.else_branch {
            None => {
                // No else: fall_through captures the "cond was false" condition.
                // The outer BlockSugar uses this as a guard for subsequent statements.
                Outcome::Complete(Desugared::StmtBlock {
                    guarded: all_guarded,
                    fall_through: vec![not_cond],
                })
            }
            Some((_, else_expr)) => {
                // The else expression is Expr::Block (plain `else { ... }`) or
                // Expr::If (an `else if ...` chain). Both are dispatched via build_stmt_role.
                let else_stmt = Stmt::Expr(*else_expr.clone(), None);
                let (else_guarded, _else_fall) = {
                    let items: Vec<Item> = Vec::new();
                    let else_fcx = SugarBuildCtx::new(ctx.scope, &options, &let_inits);
                    let else_node = build_stmt_role(&else_stmt, &else_fcx, SugarRole::Statement);
                    let reducer =
                        ReductionCtx::from_items_with_imports(&items, ctx.scope.macro_registry());
                    let mut fw = FloatWidthScope::new();
                    let else_ctx = sugar_ctx_with_factory_audits(
                        ctx.scope,
                        &options,
                        &reducer,
                        &mut fw,
                        0,
                        ctx.factory_audits,
                    );
                    match else_node.reduce(&else_ctx) {
                        Outcome::Complete(Desugared::StmtBlock {
                            guarded,
                            fall_through,
                        }) => (guarded, fall_through),
                        Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
                        _ => panic!("if_sugar: else-branch did not reduce to StmtBlock"),
                    }
                };

                for (mut guards, term) in else_guarded {
                    guards.insert(0, not_cond.clone());
                    all_guarded.push((guards, term));
                }

                // With an else branch the alternatives are exhaustive: no fall_through.
                Outcome::Complete(Desugared::StmtBlock {
                    guarded: all_guarded,
                    fall_through: vec![],
                })
            }
        }
    }
}
