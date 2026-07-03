// SPDX-License-Identifier: Apache-2.0

use std::rc::Rc;

use sugar_floor_algebra::{
    Desugared, Effect, GuardedRaise, Outcome, RaiseEffect, RouteRaiseHandler, RouteRaisesAccept,
    RouteRaisesOperation,
};
use sugar_ir_symbolic::{atomic_, num, ConstValue, Formula, Term};

fn result_err_effect() -> Effect {
    Effect::Raise(RaiseEffect::ResultErr {
        boundary: "fallible()?".to_string(),
    })
}

fn coverage_gap_effect() -> Effect {
    Effect::CoverageGap {
        boundary: "open-plugin-floor".to_string(),
        reason: "synthetic open edge".to_string(),
    }
}

fn assert_return_int(outcome: Outcome, expected: i128) {
    let Outcome::Complete(Desugared::StmtReturn(term)) = outcome else {
        panic!("expected StmtReturn");
    };
    let Term::Const {
        value: ConstValue::Int(got),
        ..
    } = &*term
    else {
        panic!("expected Int const return");
    };
    assert_eq!(*got, expected);
}

fn assert_incomplete_effect(outcome: Outcome, expected: Effect) {
    let Outcome::Incomplete(got) = outcome else {
        panic!("expected incomplete effect");
    };
    assert_eq!(format!("{got:?}"), format!("{expected:?}"));
}

struct ResultErrHandler;

impl RouteRaiseHandler for ResultErrHandler {
    fn matches(&self, effect: &Effect) -> bool {
        matches!(effect, Effect::Raise(RaiseEffect::ResultErr { .. }))
    }

    fn reduce(&self, effect: &Effect) -> Outcome {
        assert!(
            self.matches(effect),
            "handler called for non-matching effect"
        );
        Outcome::Complete(Desugared::StmtReturn(num(7)))
    }
}

#[test]
fn public_router_routes_matching_incomplete_raise() {
    let handler = ResultErrHandler;
    let outcome = RouteRaisesOperation::new(vec![&handler], "public-router-test")
        .route_incomplete(Outcome::Incomplete(result_err_effect()));

    assert_return_int(outcome, 7);
}

#[test]
fn public_router_propagates_unmatched_raise_unchanged() {
    let effect = result_err_effect();
    let outcome = RouteRaisesOperation::new(Vec::new(), "public-router-test")
        .route_incomplete(Outcome::Incomplete(effect.clone()));

    assert_incomplete_effect(outcome, effect);
}

#[test]
fn public_router_propagates_non_raise_effect_unchanged() {
    let effect = coverage_gap_effect();
    let handler = ResultErrHandler;
    let outcome = RouteRaisesOperation::new(vec![&handler], "public-router-test")
        .route_incomplete(Outcome::Incomplete(effect.clone()));

    assert_incomplete_effect(outcome, effect);
}

#[test]
fn public_router_routes_guarded_block_raise_and_preserves_guards() {
    let guard = atomic_("outer_guard", vec![]);
    let handler = ResultErrHandler;
    let outcome = RouteRaisesOperation::new(vec![&handler], "public-router-test").route_outcome(
        Outcome::Complete(Desugared::StmtBlock {
            guarded: Vec::new(),
            raises: vec![GuardedRaise::new(vec![guard.clone()], result_err_effect())],
            fall_through: Vec::new(),
        }),
    );

    let Outcome::Complete(Desugared::StmtBlock {
        guarded,
        raises,
        fall_through,
    }) = outcome
    else {
        panic!("expected routed block");
    };
    assert_eq!(guarded.len(), 1);
    assert_eq!(guarded[0].guards().len(), 1);
    assert!(Rc::ptr_eq(&guarded[0].guards()[0], &guard));
    assert!(raises.is_empty(), "handled raise must not remain residual");
    assert!(fall_through.is_empty());
}

#[test]
fn public_router_routes_nested_guarded_raise() {
    let outer = atomic_("outer_guard", vec![]);
    let inner = atomic_("inner_guard", vec![]);
    let handler = ResultErrHandler;
    let outcome = RouteRaisesOperation::new(vec![&handler], "public-router-test").route_outcome(
        Outcome::Complete(Desugared::StmtBlock {
            guarded: Vec::new(),
            raises: vec![GuardedRaise::new(
                vec![outer.clone(), inner.clone()],
                result_err_effect(),
            )],
            fall_through: Vec::new(),
        }),
    );

    let Outcome::Complete(Desugared::StmtBlock { guarded, .. }) = outcome else {
        panic!("expected routed block");
    };
    assert_eq!(guarded.len(), 1);
    assert_eq!(guarded[0].guards().len(), 2);
    assert!(Rc::ptr_eq(&guarded[0].guards()[0], &outer));
    assert!(Rc::ptr_eq(&guarded[0].guards()[1], &inner));
}

#[test]
fn public_router_leaves_unhandled_block_raise_as_data() {
    let guard: Rc<Formula> = atomic_("residual_guard", vec![]);
    let outcome = Desugared::StmtBlock {
        guarded: Vec::new(),
        raises: vec![GuardedRaise::new(vec![guard.clone()], result_err_effect())],
        fall_through: Vec::new(),
    }
    .accept_route_raises(RouteRaisesOperation::new(Vec::new(), "public-router-test"));

    let Outcome::Complete(Desugared::StmtBlock { raises, .. }) = outcome else {
        panic!("expected residual raise block");
    };
    assert_eq!(raises.len(), 1);
    assert_eq!(raises[0].guards().len(), 1);
    assert!(Rc::ptr_eq(&raises[0].guards()[0], &guard));
}
