// SPDX-License-Identifier: Apache-2.0
//
// `IteratorSugar`: the `.iter()` / `.into_iter()` identity-family adaptor over a
// sequence Sugar. It is the explicit node between a literal domain and terminals like
// `.next()`: `[1, 2, 3]` -> `LiteralSugar`, `.iter()` -> `IteratorSugar`, `.next()` ->
// `IterTerminalSugar`. Recognition claims only receivers that are already literal-resolvable
// through the Composite/literal-sequence factory gates; unknown runtime-looking receivers stay
// structural factory holes instead of being laundered into a named runtime verdict.

use syn::Expr;

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("iterator", recognize_composite);

/// COMPOSITE recognizer for identity-family iterator adaptors.
pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !call.args.is_empty() {
        return None;
    }
    match call.method.to_string().as_str() {
        "iter" | "into_iter" | "cloned" | "copied" | "fuse" | "by_ref" | "clone" => {
            Some(Box::new(IteratorSugar {
                receiver: SugarBody::from_node(method_family::build_literal_sequence_composite(
                    &call.receiver,
                    fcx,
                )?),
            }))
        }
        _ => None,
    }
}

/// Identity-family iterator adaptor. Desugars by passing through the inner sequence.
pub(crate) struct IteratorSugar {
    pub(crate) receiver: SugarBody<CompositeFloor>,
}

impl Sugar for IteratorSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.receiver.reduce(ctx) {
            Outcome::Complete(desugared) => match desugared.into_seq() {
                Some(seq) => Outcome::Complete(Desugared::Seq(seq)),
                None => iterator_gap("iterator receiver reduced to non-sequence"),
            },
            Outcome::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}

fn iterator_gap(reason: &str) -> ! {
    panic!("iterator did not reach a lawful floor: {reason}")
}
