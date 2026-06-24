// SPDX-License-Identifier: Apache-2.0
//
// Exact IEEE-754 literal method sugar for f32/f64 bit conversions.
//
// The method sugar does not inspect float receiver syntax. It owns only the operation
// call shape, reduces the typed IEEE float floor child, and dispatches to that floor for
// representation semantics.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, ExprCall, ExprMethodCall};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{IeeeFloatFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::float_floor::{
    from_bits_width, reduce_bits, IeeeFloatAccept, IeeeFloatValue, IeeeFloatVisitor, IeeeFloatWidth,
};
use crate::{token_key, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "float_literal_method",
    &["primitive_int", "call", "method"],
    recognize,
);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::MethodCall(call) => recognize_method(call, fcx),
        Expr::Call(call) => recognize_call(call, fcx),
        _ => None,
    }
}

fn recognize_method(call: &ExprMethodCall, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if call.method != "to_bits" || !call.args.is_empty() {
        return None;
    }
    Some(Box::new(FloatLiteralMethodSugar::ToBits {
        receiver: SugarBody::ieee_float(&call.receiver, fcx, None, "to_bits"),
    }))
}

fn recognize_call(call: &ExprCall, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if call.args.len() != 1 {
        return None;
    }
    let width = from_bits_width(&call.func)?;
    Some(Box::new(FloatLiteralMethodSugar::FromBits {
        width,
        bits: SugarBody::term(&call.args[0], fcx),
        site: token_key(Expr::Call(call.clone())),
    }))
}

enum FloatLiteralMethodSugar {
    ToBits {
        receiver: SugarBody<IeeeFloatFloor>,
    },
    FromBits {
        width: IeeeFloatWidth,
        bits: SugarBody<TermFloor>,
        site: String,
    },
}

impl Sugar for FloatLiteralMethodSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self {
            FloatLiteralMethodSugar::ToBits { receiver } => {
                let term = match reduce_receiver(receiver, ctx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                term.accept_ieee_float(ToBitsVisitor)
            }
            FloatLiteralMethodSugar::FromBits { width, bits, site } => {
                let bits = match reduce_bits(bits, ctx, site, "from_bits") {
                    Ok(bits) => bits,
                    Err(outcome) => return outcome,
                };
                let value = match IeeeFloatValue::from_bits(*width, bits, site) {
                    Ok(value) => value,
                    Err(outcome) => return outcome,
                };
                match value.to_real_term(site) {
                    Ok(term) => Outcome::Complete(Desugared::Term(term)),
                    Err(outcome) => outcome,
                }
            }
        }
    }
}

fn reduce_receiver(
    receiver: &SugarBody<IeeeFloatFloor>,
    ctx: &SugarCtx,
) -> Result<Rc<Term>, Outcome> {
    match receiver.reduce(ctx) {
        Outcome::Complete(desugared) => Ok(desugared
            .into_term()
            .unwrap_or_else(|| float_literal_method_gap("receiver completed as non-term"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

struct ToBitsVisitor;

impl IeeeFloatVisitor for ToBitsVisitor {
    type Output = Outcome;

    fn visit_float(self, value: IeeeFloatValue) -> Self::Output {
        Outcome::Complete(Desugared::Term(value.to_bits_term()))
    }

    fn visit_non_float(self, _term: &Rc<Term>) -> Self::Output {
        float_literal_method_gap("to_bits receiver did not dispatch to IEEE float floor")
    }
}

fn float_literal_method_gap(reason: &str) -> ! {
    panic!("float_literal_method did not reach a lawful floor: {reason}")
}
