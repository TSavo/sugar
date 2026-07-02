// SPDX-License-Identifier: Apache-2.0
//
// IrTerm boundary-collapse campaign (#3192), Slice 2 reachability tooth.

use std::panic;

use sugar_floor_algebra::{ControlFlowGuardAccept, ControlFlowGuardOperation, Desugared, Outcome};
use sugar_ir_types::{Formula as IrFormula, Sort, Term as IrTerm};
use sugar_walk::term_boundary::{lower_ir, lower_ir_formula, raise_ir, raise_ir_formula};

fn primitive(name: &str) -> Sort {
    Sort::Primitive { name: name.into() }
}

#[test]
fn sugar_walk_can_cross_boundary_and_dispatch_control_flow_guard() {
    let ir_term = IrTerm::Ctor {
        name: "method:unwrap".to_string(),
        args: vec![IrTerm::Var {
            name: "maybe".to_string(),
        }],
    };
    let lowered_term = lower_ir(&ir_term);
    assert_eq!(raise_ir(&lowered_term), ir_term);

    let ir_guard = IrFormula::Atomic {
        name: "is_some".to_string(),
        args: vec![IrTerm::Var {
            name: "maybe".to_string(),
        }],
    };
    let lowered_guard = lower_ir_formula(&ir_guard);
    assert_eq!(raise_ir_formula(&lowered_guard), ir_guard);

    let outcome = Desugared::StmtReturn(lowered_term.clone()).accept_control_flow_guard(
        ControlFlowGuardOperation::new(vec![lowered_guard.clone()], "sugar-walk.term-boundary"),
    );

    let Outcome::Complete(Desugared::StmtGuarded(guarded)) = outcome else {
        panic!("guard operation should return a guarded statement floor");
    };
    assert_eq!(guarded.guards().len(), 1);
    assert_eq!(raise_ir(guarded.term()), ir_term);
    assert_eq!(raise_ir_formula(&guarded.guards()[0]), ir_guard);
}

#[test]
fn function_sort_lowering_refuses_loudly_through_term_boundary() {
    let ir_term = IrTerm::Const {
        value: serde_json::json!(0),
        sort: Sort::Function {
            args: vec![primitive("Int")],
            ret: Box::new(primitive("Bool")),
        },
    };

    let refusal = panic::catch_unwind(|| lower_ir(&ir_term));
    let Err(payload) = refusal else {
        panic!("Function sort silently lowered through term_boundary");
    };
    let message = payload
        .downcast_ref::<String>()
        .cloned()
        .or_else(|| payload.downcast_ref::<&str>().map(|msg| (*msg).to_string()))
        .unwrap_or_else(|| "<non-string panic payload>".to_string());
    assert!(
        message.contains("not supported in symbolic Sort wrapper"),
        "Function-sort refusal should name the symbolic Sort wrapper seam: {message}"
    );
}
