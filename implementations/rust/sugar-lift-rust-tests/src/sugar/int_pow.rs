// SPDX-License-Identifier: Apache-2.0
//
// `IntPowSugar`: primitive integer `.pow(<literal exponent>)` as a compiler
// axiom. It has no effect verdict of its own: it composes typed child floors,
// or bubbles a child Incomplete unchanged.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{numeric_floor_from_term, PowVisitor};
use crate::{
    const_fold_int_term, const_fold_u128_term, strip_refs_groups, Desugared, Outcome, Sugar,
    SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("int_pow", SugarRole::Term, recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.method != "pow" || call.args.len() != 1 {
        return None;
    }
    Some(Box::new(IntPowSugar {
        receiver: SugarBody::term(&call.receiver, fcx),
        exponent: SugarBody::term(&call.args[0], fcx),
    }))
}

struct IntPowSugar {
    receiver: SugarBody<TermFloor>,
    exponent: SugarBody<TermFloor>,
}

impl Sugar for IntPowSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match term_body(&self.receiver, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let exponent = match term_body(&self.exponent, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let Some(exponent) = const_fold_int_term(&exponent)
            .or_else(|| const_fold_u128_term(&exponent).and_then(|n| i128::try_from(n).ok()))
        else {
            panic!(
                "int pow exponent did not reduce to an integer literal; write the owning Sugar before Outcome"
            );
        };
        if exponent < 0 {
            panic!("int pow exponent is negative; Rust pow exponents must be unsigned");
        }
        let exponent =
            u32::try_from(exponent).unwrap_or_else(|_| panic!("int pow exponent does not fit u32"));
        let Some(floor) = numeric_floor_from_term(&receiver) else {
            panic!(
                "int pow receiver did not reduce to a numeric floor; write the owning Sugar before Outcome"
            );
        };
        let Some(result) = floor.accept(PowVisitor { exponent }) else {
            panic!(
                "int pow numeric floor could not compute a result; write the owning typed floor before Outcome"
            );
        };
        let Some(term) = result.term() else {
            panic!("int pow numeric floor could not reify its result term");
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::int_pow",
            exponent,
            ?floor,
            ?result,
            "resolved primitive integer pow compiler axiom"
        );
        Outcome::Complete(Desugared::Term(term))
    }
}

fn term_body(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| panic!("term body completed as non-term before int pow"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}
