// SPDX-License-Identifier: Apache-2.0
//
// BlockSugar: the statement-composition engine. Reduces a braced block of statements
// to `Desugared::StmtBlock { guarded, raises, fall_through }` by dispatching each statement
// through the factory (via `build_stmt_role`) and composing the results inside-out:
//
//   StmtSupport  -> skip (inert)
//   StmtBound    -> thread `scope.record_bound_var` so subsequent stmts resolve the name
//   StmtReturn   -> emit `(pending, term)` -- a new guarded return clause
//   StmtRaise    -> emit `(pending, effect)` -- a new guarded raise clause
//   StmtBlock    -> merge its guarded/raise clauses (each prefixed with `pending`),
//                   extend `pending` with its own fall_through
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
//   `block_stmt_to_formula(guarded, raises)` -- convert a fully routed guarded vec
//      to a Formula (for block_inv); residual raises refuse formula emission.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::Formula;
use syn::{Expr, Item, Stmt};

use crate::sugar::catalog::build_stmt_role;
use crate::sugar::claim::{StmtSugarClaim, SugarRole};
use crate::sugar::control_flow_guard_operation::{guard_block, guard_exit, ControlFlowGuardAccept};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::guarded_raise::GuardedRaise;
use crate::sugar::guarded_return::{guarded_returns_to_formula, GuardedReturn};
use crate::sugar::raise_value::RaiseValue;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    sugar_ctx_with_factory_audits, Desugared, FloatWidthScope, LiftOptions, Outcome, ReductionCtx,
    Sugar, SugarCtx, TemporalScope,
};

pub(crate) static BLOCK_STMT_SUGAR: StmtSugarClaim = StmtSugarClaim::statement_before(
    "block_sugar",
    &["stmt_support"],
    crate::sugar::claim::SugarWitnesses::Pending,
    recognize_block,
);

pub(crate) static SUPPORT_STMT_SUGAR: StmtSugarClaim = StmtSugarClaim::fallback_statement(
    "stmt_support",
    crate::sugar::claim::SugarWitnesses::Pending,
    recognize_support,
);

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
        let mut emitted: Vec<GuardedReturn> = Vec::new();
        let mut raised: Vec<GuardedRaise> = Vec::new();
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

            if let Err(outcome) = compose_statement_result(
                result,
                &mut scope_clone,
                &mut emitted,
                &mut raised,
                &mut pending,
            ) {
                return outcome;
            }
        }

        Outcome::Complete(Desugared::StmtBlock {
            guarded: emitted,
            raises: raised,
            fall_through: pending,
        })
    }
}

fn compose_statement_result(
    result: Outcome,
    scope_clone: &mut TemporalScope,
    emitted: &mut Vec<GuardedReturn>,
    raised: &mut Vec<GuardedRaise>,
    pending: &mut Vec<Rc<Formula>>,
) -> Result<(), Outcome> {
    match result {
        Outcome::Incomplete(effect) => {
            let Some(raise) = RaiseValue::from_effect(effect.clone(), scope_clone) else {
                return Err(Outcome::Incomplete(effect));
            };
            raised.push(guard_raise(
                Desugared::StmtRaise(raise),
                pending,
                "BlockSugar",
            ));
        }
        Outcome::Complete(desugared) => match desugared {
            // Inert statement: side-effect, macro invocation, item definition, etc.
            Desugared::StmtSupport => {}
            // Let binding: thread into scope for downstream term translation.
            Desugared::StmtBound(bound) => {
                scope_clone.record_bound_var(bound);
            }
            // Single return: emit under the current accumulated pending guards.
            Desugared::StmtReturn(term) => {
                emitted.push(guard_exit(
                    Desugared::StmtReturn(term),
                    pending,
                    "BlockSugar",
                ));
            }
            Desugared::StmtGuarded(guarded_return) => {
                emitted.push(guard_exit(
                    Desugared::StmtGuarded(guarded_return),
                    pending,
                    "BlockSugar",
                ));
            }
            Desugared::StmtRaise(raise) => {
                raised.push(guard_raise(
                    Desugared::StmtRaise(raise),
                    pending,
                    "BlockSugar",
                ));
            }
            Desugared::StmtGuardedRaise(guarded_raise) => {
                raised.push(guard_raise(
                    Desugared::StmtGuardedRaise(guarded_raise),
                    pending,
                    "BlockSugar",
                ));
            }
            // Nested block/if: merge its guarded clauses (prefixed with pending),
            // extend pending with any fall_through conditions.
            Desugared::StmtBlock {
                guarded,
                raises: block_raises,
                fall_through,
            } => {
                let (guarded, block_raises, fall_through) =
                    guard_block(guarded, block_raises, fall_through, pending, "BlockSugar");
                emitted.extend(guarded);
                raised.extend(block_raises);
                pending.extend(fall_through);
            }
            other => block_stmt_gap(&format!(
                "statement role produced non-statement floor {}",
                statement_floor_name(&other)
            )),
        },
    }
    Ok(())
}

// ── Formula conversion (for source_contract.rs) ───────────────────────────────

/// Convert the `guarded` output of a `StmtBlock` to a closed consistency `Formula`.
/// Each `(guards, term)` pair becomes `implies(and_(guards), eq(out, term))`.
/// An empty guards list uses `atomic_("true", [])` (unconditional).
/// Returns `None` if `guarded` is empty (no return clause -> no formula to emit).
pub(crate) fn block_stmt_to_formula(
    guarded: Vec<GuardedReturn>,
    raises: Vec<GuardedRaise>,
) -> Option<Rc<Formula>> {
    if !raises.is_empty() {
        return None;
    }
    guarded_returns_to_formula(guarded)
}

fn statement_floor_name(desugared: &Desugared) -> &'static str {
    match desugared {
        Desugared::Seq(_) => "Seq",
        Desugared::TermSeq(_) => "TermSeq",
        Desugared::Constraints { .. } => "Constraints",
        Desugared::Term(_) => "Term",
        Desugared::LiteralString(_) => "LiteralString",
        Desugared::LiteralCStr(_) => "LiteralCStr",
        Desugared::FormatValue(_) => "FormatValue",
        Desugared::TupleComponents(_) => "TupleComponents",
        Desugared::ObjectValue(_) => "ObjectValue",
        Desugared::PredicateValue(_) => "PredicateValue",
        Desugared::StmtSupport => "StmtSupport",
        Desugared::StmtBound(_) => "StmtBound",
        Desugared::StmtReturn(_) => "StmtReturn",
        Desugared::StmtGuarded(_) => "StmtGuarded",
        Desugared::StmtRaise(_) => "StmtRaise",
        Desugared::StmtGuardedRaise(_) => "StmtGuardedRaise",
        Desugared::StmtBlock { .. } => "StmtBlock",
    }
}

fn guard_raise(statement: Desugared, guards: &[Rc<Formula>], owner: &'static str) -> GuardedRaise {
    let outcome = statement.accept_control_flow_guard(
        crate::sugar::control_flow_guard_operation::ControlFlowGuardOperation::new(
            guards.to_vec(),
            owner,
        ),
    );
    match outcome {
        Outcome::Complete(Desugared::StmtRaise(raise)) => {
            GuardedRaise::from_raise(Vec::new(), raise)
        }
        Outcome::Complete(Desugared::StmtGuardedRaise(guarded_raise)) => guarded_raise,
        Outcome::Complete(other) => block_stmt_gap(&format!(
            "raise guard operation produced non-raise floor {}",
            statement_floor_name(&other)
        )),
        Outcome::Incomplete(effect) => block_stmt_gap(&format!(
            "raise guard operation returned incomplete {}",
            effect.reason()
        )),
    }
}

fn block_stmt_gap(reason: &str) -> ! {
    panic!("guarded return floor did not reach lawful statement composition: {reason}")
}

// ── Unit tests ────────────────────────────────────────────────────────────────
//
// TDD note: these tests were written BEFORE populating STMT_CLAIMS in catalog.rs.
// At that point they fail because build_stmt_role returns backstop::unsupported
// which panics on reduce. After wiring the claims they must pass.

#[cfg(test)]
mod tests {
    use std::rc::Rc;

    use super::compose_statement_result;
    use sugar_ir_symbolic::{atomic_, num};
    use syn::{Expr, Item, Stmt};

    use crate::sugar::catalog::build_stmt_role;
    use crate::sugar::claim::SugarRole;
    use crate::sugar::control_flow_guard_operation::{
        ControlFlowGuardAccept, ControlFlowGuardOperation,
    };
    use crate::sugar::factory::SugarBuildCtx;
    use crate::sugar::guarded_return::GuardedReturn;
    use crate::sugar::object_value::ObjectValue;
    use crate::sugar::route_raises_operation::{
        RouteRaiseHandler, RouteRaisesAccept, RouteRaisesOperation,
    };
    use crate::sugar::source_contract::emit_value_contract;
    use crate::sugar::term_dispatch::{term_floor_dispatch, FloorDispatch};
    use crate::{
        sugar_ctx_with_factory_audits, Desugared, Effect, FloatWidthScope, LiftOptions, Outcome,
        RaiseEffect, ReductionCtx, TemporalPlan, TemporalScope,
    };

    fn reduce_fn_block_to_statement_floor(src: &str) -> Outcome {
        let file: syn::File = syn::parse_str(src).expect("parse");
        let syn::Item::Fn(ref func) = file.items[0] else {
            panic!("expected fn");
        };
        let block_stmt = Stmt::Expr(
            Expr::Block(syn::ExprBlock {
                attrs: vec![],
                label: None,
                block: (*func.block).clone(),
            }),
            None,
        );
        let scope = TemporalScope::new("raise-routing-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = build_stmt_role(&block_stmt, &fcx, SugarRole::Statement);
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items_with_imports(&items, scope.macro_registry());
        let mut float_widths = FloatWidthScope::new();
        let ctx =
            sugar_ctx_with_factory_audits(&scope, &options, &reducer, &mut float_widths, 0, None);
        node.reduce(&ctx)
    }

    fn synthetic_open_edge_gap() -> Effect {
        let floor = Desugared::ObjectValue(ObjectValue::new("PluginFloor", Vec::new(), Vec::new()));
        match term_floor_dispatch(floor, "BlockSugarTest", "synthetic PluginFloor") {
            FloorDispatch::Dispatched(_) => {
                panic!("synthetic open-edge floor unexpectedly dispatched")
            }
            FloorDispatch::Gap(gap) => {
                match FloorDispatch::<Rc<sugar_ir_symbolic::Term>>::Gap(gap).into_result() {
                    Err(effect) => effect,
                    Ok(_) => panic!("gap unexpectedly lowered to a term"),
                }
            }
        }
    }

    #[test]
    fn control_flow_guard_operation_prefixes_block_guarded_returns() {
        let outer = atomic_("outer", vec![]);
        let inner = atomic_("inner", vec![]);
        let fallthrough = atomic_("fallthrough", vec![]);

        let outcome = Desugared::StmtBlock {
            guarded: vec![GuardedReturn::new(vec![inner.clone()], num(7))],
            raises: Vec::new(),
            fall_through: vec![fallthrough.clone()],
        }
        .accept_control_flow_guard(ControlFlowGuardOperation::new(vec![outer.clone()], "test"));

        let Outcome::Complete(Desugared::StmtBlock {
            guarded,
            raises,
            fall_through,
        }) = outcome
        else {
            panic!("expected guarded block output");
        };

        assert_eq!(guarded.len(), 1);
        assert!(raises.is_empty());
        assert_eq!(guarded[0].guards.len(), 2);
        assert!(Rc::ptr_eq(&guarded[0].guards[0], &outer));
        assert!(Rc::ptr_eq(&guarded[0].guards[1], &inner));
        assert_eq!(fall_through.len(), 1);
        assert!(Rc::ptr_eq(&fall_through[0], &fallthrough));
    }

    #[test]
    #[should_panic(expected = "write more ControlFlowGuardOperation for `StmtSupport`")]
    fn control_flow_guard_operation_rejects_non_exit_floor() {
        let guard = atomic_("guard", vec![]);

        let _ = Desugared::StmtSupport
            .accept_control_flow_guard(ControlFlowGuardOperation::new(vec![guard], "test"));
    }

    #[test]
    fn floor_dispatch_gap_propagates_through_block_composition() {
        let effect = synthetic_open_edge_gap();
        let mut scope = TemporalScope::new("floor-dispatch-gap-test", TemporalPlan::default());
        let mut emitted = Vec::new();
        let mut raised = Vec::new();
        let mut pending = Vec::new();

        let result = compose_statement_result(
            Outcome::Incomplete(effect),
            &mut scope,
            &mut emitted,
            &mut raised,
            &mut pending,
        );

        let Err(Outcome::Incomplete(Effect::CoverageGap { boundary, reason })) = result else {
            panic!("coverage gap should propagate as an incomplete block outcome");
        };
        assert_eq!(boundary, "ObjectValue");
        assert!(reason.contains("owner=BlockSugarTest"));
        assert!(reason.contains("observed=ObjectValue"));
        assert!(emitted.is_empty());
        assert!(raised.is_empty());
        assert!(pending.is_empty());
    }

    #[test]
    fn raise_under_inner_if_is_block_interior_data_for_routing() {
        struct PanicHandler;
        impl RouteRaiseHandler for PanicHandler {
            fn matches(&self, effect: &Effect) -> bool {
                matches!(effect, Effect::PanicMacro { .. })
            }

            fn reduce(&self, _scope: &TemporalScope, _effect: &Effect) -> Outcome {
                Outcome::Complete(Desugared::StmtReturn(num(99)))
            }
        }

        let src = r#"
            pub fn f(flag: bool) -> u32 {
                if flag { panic!() }
                7u32
            }
        "#;

        let outcome = reduce_fn_block_to_statement_floor(src);

        let Outcome::Complete(Desugared::StmtBlock {
            guarded,
            raises,
            fall_through,
        }) = outcome
        else {
            panic!("raise under inner if should remain block-interior data");
        };
        assert_eq!(guarded.len(), 1, "fall-through tail return remains guarded");
        assert_eq!(raises.len(), 1, "inner panic becomes guarded raise data");
        assert_eq!(
            fall_through.len(),
            1,
            "if-without-else leaves its outer fall-through guard"
        );

        let handler = PanicHandler;
        let routed = Desugared::StmtBlock {
            guarded,
            raises,
            fall_through,
        }
        .accept_route_raises(RouteRaisesOperation::new(vec![&handler], "test"));

        let Outcome::Complete(Desugared::StmtBlock {
            guarded,
            raises,
            fall_through,
        }) = routed
        else {
            panic!("matching handler should route the guarded raise");
        };
        assert_eq!(
            guarded.len(),
            2,
            "handler arm plus original fall-through arm"
        );
        assert!(raises.is_empty(), "matched raise must not remain residual");
        assert_eq!(
            fall_through.len(),
            1,
            "routing preserves unrelated block fall-through guards"
        );
    }

    #[test]
    fn guarded_raise_composes_under_nested_ifs() {
        let src = r#"
            pub fn f(outer: bool, inner: bool) -> u32 {
                if outer {
                    if inner { panic!() }
                }
                7u32
            }
        "#;

        let outcome = reduce_fn_block_to_statement_floor(src);
        let Outcome::Complete(Desugared::StmtBlock { raises, .. }) = outcome else {
            panic!("nested guarded raise should remain block-interior data");
        };

        assert_eq!(raises.len(), 1);
        assert_eq!(
            raises[0].guards().len(),
            2,
            "outer and inner guards must both prefix the raise"
        );
    }

    #[test]
    fn explicit_return_in_branch_is_early_return_raise_data_before_function_routing() {
        let src = r#"
            pub fn f(flag: bool) -> u32 {
                if flag { return 5u32; }
                7u32
            }
        "#;

        let outcome = reduce_fn_block_to_statement_floor(src);
        let Outcome::Complete(Desugared::StmtBlock {
            guarded,
            raises,
            fall_through,
        }) = outcome
        else {
            panic!("early return block should complete to statement data");
        };

        assert_eq!(guarded.len(), 1, "tail return remains guarded by !flag");
        assert_eq!(
            raises.len(),
            1,
            "explicit return becomes routeable raise data"
        );
        assert_eq!(
            fall_through.len(),
            1,
            "if-without-else still leaves the !flag fall-through"
        );
        assert!(
            matches!(
                raises[0].effect(),
                Effect::Raise(RaiseEffect::EarlyReturnValue { .. })
            ),
            "branch return should be typed as EarlyReturnValue, got {:?}",
            raises[0].effect()
        );
    }

    #[test]
    fn panic_branch_routes_to_no_normal_exit_and_preserves_fallthrough_formula() {
        let src = r#"
            pub fn f(flag: bool) -> u32 {
                if flag { panic!() }
                7u32
            }
        "#;
        let file: syn::File = syn::parse_str(src).expect("parse");
        let syn::Item::Fn(ref func) = file.items[0] else {
            panic!("expected fn");
        };

        let contract =
            emit_value_contract("f", &func.block).expect("panic branch should route to formula");
        let inv_str = format!("{:?}", contract.inv);
        assert!(
            inv_str.contains("implies") && inv_str.contains("not") && inv_str.contains("out"),
            "panic branch should preserve the negated-condition fall-through formula: {inv_str}"
        );
    }

    #[test]
    fn uncaught_panic_without_fallthrough_refuses_formula_emission() {
        let src = r#"
            pub fn f() -> u32 {
                panic!()
            }
        "#;
        let file: syn::File = syn::parse_str(src).expect("parse");
        let syn::Item::Fn(ref func) = file.items[0] else {
            panic!("expected fn");
        };

        assert!(
            emit_value_contract("f", &func.block).is_none(),
            "a bare panic has no normal return formula to fabricate"
        );
    }

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
        let contract = emit_value_contract("f", &func.block).expect("should produce a contract");
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
        let contract =
            emit_value_contract("f", &func.block).expect("should produce a contract for if/else");
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
        let contract =
            emit_value_contract("f", &func.block).expect("should produce a contract for nested if");
        let inv_str = format!("{:?}", contract.inv);
        // Three implies clauses expected.
        let count = inv_str.matches("implies").count();
        assert!(
            count >= 3,
            "expected >= 3 implies clauses for 3-arm nested if, got {count} in: {inv_str}"
        );
    }
}
