// SPDX-License-Identifier: Apache-2.0
//
// `RevSugar`: the `.rev()` adaptor (and the synthetic final `Rev` appended for
// `.rfold`). A decorator `Sugar` over an inner sequence-`Sugar` that reverses the
// element sequence. Lifted verbatim from the `Adaptor::Rev` arm of the former
// `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::factory::{has_composite, CompositeFloor, FloorRead, SugarBody, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "rev",
        crate::sugar::claim::SugarWitnesses::temporal_campaign("S5 adapter family: rev ordering"),
        recognize_composite,
    );

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method == "rev" && call.args.is_empty() {
        if !has_composite(&call.receiver, fcx) {
            return None;
        }
        return Some(Box::new(RevSugar {
            inner: SugarBody::composite(&call.receiver, fcx),
        }));
    }
    None
}

/// Reverse the inner element sequence.
pub(crate) struct RevSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
}

impl Sugar for RevSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let mut seq = match self.inner.reduce_sequence(ctx, "rev receiver sequence") {
            FloorRead::Complete(seq) => seq,
            FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        seq.reverse();
        Outcome::Complete(Desugared::Seq(seq))
    }
}
