// SPDX-License-Identifier: Apache-2.0
//
// BoolBitwiseSugar: Rust permits `&` and `|` over `bool`. In assertion
// position, those are first-order conjunction/disjunction after each side has
// been lowered by the constraint factory.

use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_constraint, SugarBuildCtx};
use crate::{
    AssertionFactKind, Desugared, Effect, Outcome, Sugar, SugarCtx, Warrant,
    STRUCTURAL_BACKSTOP_REASON,
};
use sugar_ir_symbolic::{and_, or_, Formula};
use syn::{BinOp, Expr, ExprBinary};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("constraint_bool_bitwise", SugarRole::Constraint, recognize);

struct BoolBitwiseSugar {
    left: Box<dyn Sugar>,
    right: Box<dyn Sugar>,
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
        left: build_constraint(&binary.left, fcx),
        right: build_constraint(&binary.right, fcx),
        is_and,
    }))
}

impl Sugar for BoolBitwiseSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let left = match constraint_payload(&*self.left, ctx) {
            Ok(payload) => payload,
            Err(outcome) => return outcome,
        };
        let right = match constraint_payload(&*self.right, ctx) {
            Ok(payload) => payload,
            Err(outcome) => return outcome,
        };
        let atom = if self.is_and {
            and_(vec![left.atom, right.atom])
        } else {
            or_(vec![left.atom, right.atom])
        };
        Outcome::Dug(Desugared::Constraints {
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

fn constraint_payload(node: &dyn Sugar, ctx: &SugarCtx) -> Result<ConstraintPayload, Outcome> {
    match node.desugar(ctx) {
        Outcome::Dug(Desugared::Constraints {
            atom,
            kind,
            warrant,
            ..
        }) => Ok(ConstraintPayload {
            atom,
            kind,
            name: warrant.name,
        }),
        Outcome::Dug(_) => Err(Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })),
        Outcome::Hit(effect) => Err(Outcome::Hit(effect)),
    }
}

fn common_constraint_name(left: &Option<String>, right: &Option<String>) -> Option<String> {
    match (left, right) {
        (Some(left), Some(right)) if left == right => Some(left.clone()),
        _ => None,
    }
}
