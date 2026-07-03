// SPDX-License-Identifier: Apache-2.0

use sugar_floor_algebra::{
    Desugared, Effect, GuardedRaise, Outcome, RaiseEffect, RouteRaiseHandler, RouteRaisesOperation,
};
use sugar_ir_types as ir;
use sugar_walk::term_boundary::{lower_ir, lower_ir_formula, raise_ir, raise_ir_formula};

fn primitive(name: &str) -> ir::Sort {
    ir::Sort::Primitive { name: name.into() }
}

fn int_const(value: i64) -> ir::Term {
    ir::Term::Const {
        value: serde_json::json!(value),
        sort: primitive("Int"),
    }
}

fn guard_formula(name: &str) -> ir::Formula {
    ir::Formula::Atomic {
        name: name.into(),
        args: Vec::new(),
    }
}

fn result_err_effect() -> Effect {
    Effect::Raise(RaiseEffect::ResultErr {
        boundary: "fallible()?".to_string(),
    })
}

struct ResultErrHandler;

impl RouteRaiseHandler for ResultErrHandler {
    fn matches(&self, effect: &Effect) -> bool {
        matches!(effect, Effect::Raise(RaiseEffect::ResultErr { .. }))
    }

    fn reduce(&self, effect: &Effect) -> Outcome {
        assert!(self.matches(effect), "handler called for non-result raise");
        Outcome::Complete(Desugared::StmtReturn(lower_ir(&int_const(7))))
    }
}

#[test]
fn boundary_routes_raise_under_inner_if_with_wrapping_handler() {
    let outer = guard_formula("outer_if");
    let inner = guard_formula("inner_if");
    let handler = ResultErrHandler;
    let outcome = RouteRaisesOperation::new(vec![&handler], "sugar-walk-route-raises")
        .route_outcome(Outcome::Complete(Desugared::StmtBlock {
            guarded: Vec::new(),
            raises: vec![GuardedRaise::new(
                vec![lower_ir_formula(&outer), lower_ir_formula(&inner)],
                result_err_effect(),
            )],
            fall_through: Vec::new(),
        }));

    let Outcome::Complete(Desugared::StmtBlock {
        guarded,
        raises,
        fall_through,
    }) = outcome
    else {
        panic!("expected routed statement block");
    };

    assert_eq!(guarded.len(), 1);
    assert_eq!(guarded[0].guards().len(), 2);
    assert_eq!(raise_ir_formula(&guarded[0].guards()[0]), outer);
    assert_eq!(raise_ir_formula(&guarded[0].guards()[1]), inner);
    assert_eq!(raise_ir(guarded[0].term()), int_const(7));
    assert!(raises.is_empty(), "handled raise must not remain residual");
    assert!(fall_through.is_empty());
}

#[test]
fn boundary_keeps_uncaught_raise_as_residual_effect() {
    let guard = guard_formula("residual_if");
    let effect = result_err_effect();
    let outcome = RouteRaisesOperation::new(Vec::new(), "sugar-walk-route-raises").route_outcome(
        Outcome::Complete(Desugared::StmtBlock {
            guarded: Vec::new(),
            raises: vec![GuardedRaise::new(
                vec![lower_ir_formula(&guard)],
                effect.clone(),
            )],
            fall_through: Vec::new(),
        }),
    );

    let Outcome::Complete(Desugared::StmtBlock {
        guarded,
        raises,
        fall_through,
    }) = outcome
    else {
        panic!("expected residual statement block");
    };

    assert!(
        guarded.is_empty(),
        "uncaught raise must not fabricate a return"
    );
    assert_eq!(raises.len(), 1);
    assert_eq!(raise_ir_formula(&raises[0].guards()[0]), guard);
    assert_eq!(raises[0].effect(), &effect);
    assert!(fall_through.is_empty());
}
