// SPDX-License-Identifier: Apache-2.0
//
// `SkipSugar`: the `.skip(n)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that drops the first `n` elements. Lifted verbatim from the
// `Adaptor::Skip(n)` arm of the former `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::{const_int, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("skip", recognize_composite);

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "skip" || call.args.len() != 1 {
        return None;
    }
    if !has_composite(&call.receiver, fcx) {
        return None;
    }
    let n: usize = const_int(&call.args[0])?.try_into().ok()?;
    Some(Box::new(SkipSugar {
        inner: SugarBody::composite(&call.receiver, fcx),
        n,
    }))
}

/// Drop the first `n` elements of the inner sequence.
pub(crate) struct SkipSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) n: usize,
}

impl Sugar for SkipSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.inner.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_seq()
                .unwrap_or_else(|| skip_gap("skip receiver reduced to non-sequence")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let out = seq.into_iter().skip(self.n).collect();
        Outcome::Complete(Desugared::Seq(out))
    }
}

fn skip_gap(reason: &str) -> ! {
    panic!("skip did not reach a lawful floor: {reason}")
}
