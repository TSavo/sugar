// SPDX-License-Identifier: Apache-2.0
//
// `WrappingNegSugar`: primitive integer `.wrapping_neg()` over a grounded literal is
// a stdlib/compiler axiom. The receiver child owns the numeric floor; this sugar only
// asks that floor to perform the typed wrapping operation and reifies the result.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{numeric_floor_from_term, WrappingNegVisitor};
use crate::{strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("wrapping_neg", SugarRole::Term, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.method != "wrapping_neg" || !call.args.is_empty() {
        return None;
    }
    Some(Box::new(WrappingNegSugar {
        receiver: SugarBody::term(&call.receiver, fcx),
    }))
}

struct WrappingNegSugar {
    receiver: SugarBody<TermFloor>,
}

impl Sugar for WrappingNegSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match term_body(&self.receiver, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let Some(floor) = numeric_floor_from_term(&receiver) else {
            panic!(
                "wrapping_neg receiver did not reduce to a numeric floor; write the owning Sugar before Outcome"
            );
        };
        let Some(result) = floor.accept(WrappingNegVisitor) else {
            panic!(
                "wrapping_neg numeric floor could not compute a result; write the owning typed floor before Outcome"
            );
        };
        let Some(term) = result.term() else {
            panic!("wrapping_neg numeric floor could not reify its result term");
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::wrapping_neg",
            ?floor,
            ?result,
            "resolved primitive wrapping_neg stdlib axiom to literal"
        );
        Outcome::Complete(Desugared::Term(term))
    }
}

fn term_body(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| panic!("term body completed as non-term before wrapping_neg"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}
