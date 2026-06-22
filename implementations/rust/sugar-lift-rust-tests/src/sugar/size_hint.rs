// SPDX-License-Identifier: Apache-2.0
//
// `size_hint` — a delayed tuple-valued PRODUCER for the shared `tuple_decomp` arm.
//
// The recognizer only owns the source shape: `<finite-composite>.size_hint()`.
// The decomposition is delayed until `desugar`, where the receiver is asked through
// the composite factory. If it reaches a finite sequence, std `ExactSizeIterator`
// semantics give `(len, Some(len))`; if it hits an effect/runtime boundary, that
// boundary propagates. Empty literal domains are inert and contribute length zero.

use sugar_ir_symbolic::num;
use syn::Expr;
use tracing::debug;

use crate::sugar::factory::{build_composite, has_composite, SugarBuildCtx};
use crate::sugar::literal::EMPTY_DOMAIN_REASON;
use crate::sugar::monadic;
use crate::{Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const TUPLE_PRODUCER_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::tuple_producer("size_hint_tuple_producer", recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "size_hint" || !call.args.is_empty() {
        return None;
    }
    if !has_composite(&call.receiver, fcx) {
        return None;
    }
    Some(Box::new(SizeHintTupleProducer {
        receiver: build_composite(&call.receiver, fcx),
    }))
}

struct SizeHintTupleProducer {
    receiver: Box<dyn Sugar>,
}

impl Sugar for SizeHintTupleProducer {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.receiver.desugar(ctx) {
            Outcome::Dug(desugared) => match desugared.into_seq() {
                Some(seq) => seq,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(Effect::Unsupported { reason }) if reason == EMPTY_DOMAIN_REASON => {
                Vec::new()
            }
            Outcome::Hit(effect) => return Outcome::Hit(effect),
        };
        let len = seq.len();
        debug!(
            target: "sugar_lift_rust_tests::sugar::size_hint",
            len,
            "resolved finite composite size_hint to tuple components"
        );
        Outcome::Dug(Desugared::TupleComponents(vec![
            num(len as i128),
            monadic::some_term(num(len as i128)),
        ]))
    }
}
