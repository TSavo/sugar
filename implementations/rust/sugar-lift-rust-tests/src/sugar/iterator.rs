// SPDX-License-Identifier: Apache-2.0
//
// `IteratorSugar`: the `.iter()` / `.into_iter()` identity-family adaptor over a
// sequence Sugar. It is the explicit node between a composite domain and terminals like
// `.next()`: `[1, 2, 3]` -> `LiteralSugar`, `.iter()` -> `IteratorSugar`, `.next()` ->
// `IterTerminalSugar`. The adaptor itself is boring: it delegates to the receiver's
// Composite body and bubbles any effect owned by that receiver.

use syn::Expr;

use crate::sugar::factory::{has_composite, CompositeFloor, FloorRead, SugarBody, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("iterator", recognize_composite);

/// COMPOSITE recognizer for identity-family iterator adaptors.
pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !call.args.is_empty() {
        return None;
    }
    match call.method.to_string().as_str() {
        "iter" | "into_iter" | "cloned" | "copied" | "fuse" | "by_ref" | "clone" => {
            if !has_composite(&call.receiver, fcx) {
                return None;
            }
            Some(Box::new(IteratorSugar {
                receiver: SugarBody::composite(&call.receiver, fcx),
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
        match self
            .receiver
            .reduce_sequence(ctx, "iterator identity adaptor receiver")
        {
            FloorRead::Complete(seq) => Outcome::Complete(Desugared::Seq(seq)),
            FloorRead::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}
