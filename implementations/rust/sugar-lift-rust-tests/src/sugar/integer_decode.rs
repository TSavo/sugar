// SPDX-License-Identifier: Apache-2.0
//
// `integer_decode` — a tuple-valued PRODUCER for the shared `tuple_decomp` arm.
//
// The producer owns the method shape only. The receiver is a typed IEEE float floor;
// desugar reduces that child and dispatches `integer_decode` to the floor specialization
// that owns f32/f64 bits, signed zero, infinities, and NaN boundaries.

use std::rc::Rc;

use sugar_ir_symbolic::num;
use sugar_ir_symbolic::Term;
use syn::Expr;

use crate::sugar::factory::{IeeeFloatFloor, SugarBody, SugarBuildCtx};
use crate::sugar::float_floor::{IeeeFloatAccept, IeeeFloatValue, IeeeFloatVisitor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const TUPLE_PRODUCER_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::tuple_producer(
        "integer_decode_tuple_producer",
        crate::sugar::claim::SugarWitnesses::Pending,
        recognize_tuple_producer,
    );

fn recognize_tuple_producer(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "integer_decode" || !call.args.is_empty() {
        return None;
    }
    Some(Box::new(IntegerDecodeTupleProducer {
        receiver: SugarBody::ieee_float(&call.receiver, fcx, None, "integer_decode"),
    }))
}

struct IntegerDecodeTupleProducer {
    receiver: SugarBody<IeeeFloatFloor>,
}

impl Sugar for IntegerDecodeTupleProducer {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let term = match reduce_receiver(&self.receiver, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        term.accept_ieee_float(IntegerDecodeVisitor)
    }
}

fn reduce_receiver(
    receiver: &SugarBody<IeeeFloatFloor>,
    ctx: &SugarCtx,
) -> Result<Rc<Term>, Outcome> {
    match receiver.reduce(ctx) {
        Outcome::Complete(desugared) => Ok(desugared
            .into_term()
            .unwrap_or_else(|| integer_decode_gap("receiver completed as non-term"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

struct IntegerDecodeVisitor;

impl IeeeFloatVisitor for IntegerDecodeVisitor {
    type Output = Outcome;

    fn visit_float(self, value: IeeeFloatValue) -> Self::Output {
        let (mantissa, exponent, sign) = value.integer_decode();
        Outcome::Complete(Desugared::TupleComponents(vec![
            num(i128::from(mantissa)),
            num(i128::from(exponent)),
            num(i128::from(sign)),
        ]))
    }

    fn visit_non_float(self, _term: &Rc<Term>) -> Self::Output {
        integer_decode_gap("receiver did not dispatch to IEEE float floor")
    }
}

fn integer_decode_gap(reason: &str) -> ! {
    panic!("integer_decode did not reach a lawful float floor: {reason}")
}
