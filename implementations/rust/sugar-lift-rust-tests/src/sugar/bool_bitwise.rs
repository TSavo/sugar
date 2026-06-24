// SPDX-License-Identifier: Apache-2.0
//
// BoolBitwiseSugar: Rust permits `&` and `|` over `bool`. In assertion
// position, those are first-order conjunction/disjunction after each side has
// been lowered by the constraint factory.

use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{ConstraintFloor, SugarBody, SugarBuildCtx};
use crate::{AssertionFactKind, Desugared, Outcome, Sugar, SugarCtx, Warrant};
use sugar_ir_symbolic::{and_, or_, Formula};
use syn::{BinOp, Expr, ExprBinary};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("constraint_bool_bitwise", SugarRole::Constraint, recognize);

struct BoolBitwiseSugar {
    left: SugarBody<ConstraintFloor>,
    right: SugarBody<ConstraintFloor>,
    is_and: bool,
}

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Paren(paren) => recognize(&paren.expr, fcx),
        Expr::Group(group) => recognize(&group.expr, fcx),
        Expr::Binary(binary) => recognize_binary(binary, fcx),
        _ => None,
    }
}

fn recognize_binary(binary: &ExprBinary, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let is_and = match binary.op {
        BinOp::BitAnd(_) => true,
        BinOp::BitOr(_) => false,
        _ => return None,
    };
    Some(Box::new(BoolBitwiseSugar {
        left: SugarBody::constraint(&binary.left, fcx),
        right: SugarBody::constraint(&binary.right, fcx),
        is_and,
    }))
}

impl Sugar for BoolBitwiseSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let left = match constraint_payload(&self.left, ctx) {
            Ok(payload) => payload,
            Err(outcome) => return outcome,
        };
        let right = match constraint_payload(&self.right, ctx) {
            Ok(payload) => payload,
            Err(outcome) => return outcome,
        };
        let atom = if self.is_and {
            and_(vec![left.atom, right.atom])
        } else {
            or_(vec![left.atom, right.atom])
        };
        Outcome::Complete(Desugared::Constraints {
            atom,
            n: 1,
            kind: if left.kind.is_warranted() || right.kind.is_warranted() {
                AssertionFactKind::Warranted
            } else {
                AssertionFactKind::Support
            },
            warrant: Warrant {
                name: common_constraint_name(&left.name, &right.name),
            },
        })
    }
}

struct ConstraintPayload {
    atom: Rc<Formula>,
    kind: AssertionFactKind,
    name: Option<String>,
}

fn constraint_payload(
    body: &SugarBody<ConstraintFloor>,
    ctx: &SugarCtx,
) -> Result<ConstraintPayload, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(Desugared::Constraints {
            atom,
            kind,
            warrant,
            ..
        }) => Ok(ConstraintPayload {
            atom,
            kind,
            name: warrant.name,
        }),
        Outcome::Complete(_) => bool_bitwise_gap("child reduced to a non-constraint floor"),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn common_constraint_name(left: &Option<String>, right: &Option<String>) -> Option<String> {
    match (left, right) {
        (Some(left), Some(right)) if left == right => Some(left.clone()),
        _ => None,
    }
}

fn bool_bitwise_gap(reason: &str) -> ! {
    panic!("bool_bitwise did not reach a lawful floor: {reason}")
}
