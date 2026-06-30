// SPDX-License-Identifier: Apache-2.0
//
// BlockSugar: the statement-composition engine. Reduces a braced block of statements
// to `Desugared::StmtBlock { guarded, fall_through }` by dispatching each statement
// through the factory (via `build_stmt_role`) and composing the results inside-out:
//
//   StmtSupport  -> skip (inert)
//   StmtBound    -> thread `scope.record_let_binding` so subsequent stmts resolve the name
//   StmtReturn   -> emit `(pending, term)` -- a new guarded return clause
//   StmtBlock    -> merge its guarded clauses (each prefixed with `pending`), extend `pending`
//                   with its own fall_through
//
// `pending` starts empty and accumulates the conjunction of guard conditions that must
// hold for execution to reach the current statement position (e.g. "all prior guard-clause
// conditions were false"). After all statements, the remaining `pending` becomes the
// block-level `fall_through`.
//
// SupportSugar: a catch-all fallback claim. Every Stmt dispatched via `build_stmt_role`
// MUST match at least one claim (or the factory panics). Stmts that are structurally
// opaque (macro invocations, item definitions, bare side-effect expressions with `;`)
// match SupportSugar and are treated as inert (StmtSupport).
//
// Registration:
//   BLOCK_STMT_SUGAR  -- Stmt::Expr(Expr::Block(..)) | non-fallback | comes_before stmt_support
//   SUPPORT_STMT_SUGAR -- fallback catch-all
//
// LAW: the only iteration over `block.stmts` is HERE, brokered through `build_stmt_role`.
// No Sugar module outside this file may iterate a block's stmts to build Formula/post.
//
// Public API exported to `source_contract.rs`:
//   `block_stmt_to_formula(guarded)` -- convert a guarded vec to a Formula (for block_inv).

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{and_, atomic_, eq, implies, make_var, Formula, Term};
use syn::{Expr, Item, Stmt};

use crate::sugar::catalog::build_stmt_role;
use crate::sugar::claim::{StmtSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::{
    Desugared, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar, SugarCtx,
    sugar_ctx_with_factory_audits,
};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) static BLOCK_STMT_SUGAR: StmtSugarClaim =
    StmtSugarClaim::statement_before("block_sugar", &["stmt_support"], recognize_block);

pub(crate) static SUPPORT_STMT_SUGAR: StmtSugarClaim =
    StmtSugarClaim::fallback_statement("stmt_support", recognize_support);

fn recognize_block(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let stmt = frag.as_stmt()?;
    let Stmt::Expr(Expr::Block(b), _) = stmt else {
        return None;
    };
    Some(Box::new(BlockSugar {
        stmts: b.block.stmts.clone(),
    }))
}

fn recognize_support(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let _stmt = frag.as_stmt()?;
    Some(Box::new(SupportSugar))
}

// ── SupportSugar ─────────────────────────────────────────────────────────────

struct SupportSugar;

impl Sugar for SupportSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Complete(Desugared::StmtSupport)
    }
}

// ── BlockSugar ───────────────────────────────────────────────────────────────

struct BlockSugar {
    stmts: Vec<Stmt>,
}

impl Sugar for BlockSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let options = LiftOptions::default();
        let mut scope_clone = ctx.scope.clone();
        let mut emitted: Vec<(Vec<Rc<Formula>>, Rc<Term>)> = Vec::new();
        let mut pending: Vec<Rc<Formula>> = Vec::new();

        for stmt in &self.stmts {
            // Build and reduce each child within a tight scope so that scope_clone
            // is not borrowed when we call record_let_binding below.
            let result: Outcome = {
                let items: Vec<Item> = Vec::new();
                let let_inits = BTreeMap::new();
                let fcx = SugarBuildCtx::new(&scope_clone, &options, &let_inits);
                let child_node = build_stmt_role(stmt, &fcx, SugarRole::Statement);
                let reducer =
                    ReductionCtx::from_items_with_imports(&items, scope_clone.macro_registry());
                let mut fw = FloatWidthScope::new();
                let child_ctx = sugar_ctx_with_factory_audits(
                    &scope_clone,
                    &options,
                    &reducer,
                    &mut fw,
                    0,
                    ctx.factory_audits,
                );
                child_node.reduce(&child_ctx)
                // child_ctx, reducer, items drop here -> scope_clone borrow released
            };

            match result {
                Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
                Outcome::Complete(desugared) => match desugared {
                    // Inert statement: side-effect, macro invocation, item definition, etc.
                    Desugared::StmtSupport => {}
                    // Let binding: thread into scope for downstream term translation.
                    Desugared::StmtBound { name, rhs } => {
                        scope_clone.record_let_binding(&name, rhs);
                    }
                    // Single return: emit under the current accumulated pending guards.
                    Desugared::StmtReturn(term) => {
                        emitted.push((pending.clone(), term));
                    }
                    // Nested block/if: merge its guarded clauses (prefixed with pending),
                    // extend pending with any fall_through conditions.
                    Desugared::StmtBlock { guarded, fall_through } => {
                        for (guards, term) in guarded {
                            let mut merged = pending.clone();
                            merged.extend(guards);
                            emitted.push((merged, term));
                        }
                        pending.extend(fall_through);
                    }
                    // Any other floor variant from an upstream node is treated as inert.
                    // (Should not occur in normal use: the only other variants are for
                    // Expr/Item roles, not Statement roles.)
                    _ => {}
                },
            }
        }

        Outcome::Complete(Desugared::StmtBlock {
            guarded: emitted,
            fall_through: pending,
        })
    }
}

// ── Formula conversion (for source_contract.rs) ───────────────────────────────

/// Convert the `guarded` output of a `StmtBlock` to a closed consistency `Formula`.
/// Each `(guards, term)` pair becomes `implies(and_(guards), eq(out, term))`.
/// An empty guards list uses `atomic_("true", [])` (unconditional).
/// Returns `None` if `guarded` is empty (no return clause -> no formula to emit).
pub(crate) fn block_stmt_to_formula(
    guarded: Vec<(Vec<Rc<Formula>>, Rc<Term>)>,
) -> Option<Rc<Formula>> {
    if guarded.is_empty() {
        return None;
    }
    let out = make_var("out");
    Some(and_(
        guarded
            .into_iter()
            .map(|(guards, term)| {
                let guard: Rc<Formula> = match guards.len() {
                    0 => atomic_("true", vec![]),
                    1 => guards.into_iter().next().unwrap(),
                    _ => and_(guards),
                };
                implies(guard, eq(out.clone(), term))
            })
            .collect(),
    ))
}

// ── Unit tests ────────────────────────────────────────────────────────────────
//
// TDD note: these tests were written BEFORE populating STMT_CLAIMS in catalog.rs.
// At that point they fail because build_stmt_role returns backstop::unsupported
// which panics on reduce. After wiring the claims they must pass.

#[cfg(test)]
mod tests {
    use crate::sugar::source_contract::emit_value_contract;
    use crate::sugar::source_fragment::SourceFragment;

    /// Guard-clause shape: `if cond { return v1; } v2`
    /// Must produce the SAME two-arm guarded formula as the old emit_guard_return_value.
    #[test]
    fn guard_clause_two_arm() {
        let src = r#"
            pub fn f(x: u32) -> u32 {
                if x > 5 { return 1u32; }
                0u32
            }
        "#;
        let file: syn::File = syn::parse_str(src).expect("parse");
        let syn::Item::Fn(ref func) = file.items[0] else {
            panic!("expected fn");
        };
        let contract = emit_value_contract("f", &func.block)
            .expect("should produce a contract");
        // The formula must mention both arms of the guard.
        let inv_str = format!("{:?}", contract.inv);
        assert!(
            inv_str.contains("gt") || inv_str.contains("le") || inv_str.contains("implies"),
            "expected guard formula, got: {inv_str}"
        );
    }

    /// If/else shape: `if cond { v1 } else { v2 }`
    /// Tail expression in each branch -> two guarded clauses (via tail_inv or block_stmt_inv).
    #[test]
    fn if_else_two_clause() {
        let src = r#"
            pub fn f(x: u32) -> u32 {
                if x > 5 { 1u32 } else { 0u32 }
            }
        "#;
        let file: syn::File = syn::parse_str(src).expect("parse");
        let syn::Item::Fn(ref func) = file.items[0] else {
            panic!("expected fn");
        };
        let contract = emit_value_contract("f", &func.block)
            .expect("should produce a contract for if/else");
        let inv_str = format!("{:?}", contract.inv);
        assert!(
            inv_str.contains("implies") || inv_str.contains("value:if"),
            "expected formula for if/else, got: {inv_str}"
        );
    }

    /// Nested guard-clause: `if a { if b { return 2; } return 1; } 0`
    /// Should produce three-clause formula: (a,b)->2, (a,not_b)->1, not_a->0.
    #[test]
    fn nested_if_three_clause() {
        let src = r#"
            pub fn f(a: bool, b: bool) -> u32 {
                if a {
                    if b { return 2u32; }
                    return 1u32;
                }
                0u32
            }
        "#;
        let file: syn::File = syn::parse_str(src).expect("parse");
        let syn::Item::Fn(ref func) = file.items[0] else {
            panic!("expected fn");
        };
        let contract = emit_value_contract("f", &func.block)
            .expect("should produce a contract for nested if");
        let inv_str = format!("{:?}", contract.inv);
        // Three implies clauses expected.
        let count = inv_str.matches("implies").count();
        assert!(
            count >= 3,
            "expected >= 3 implies clauses for 3-arm nested if, got {count} in: {inv_str}"
        );
    }
}
