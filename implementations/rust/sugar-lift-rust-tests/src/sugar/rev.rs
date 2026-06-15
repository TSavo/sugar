// SPDX-License-Identifier: Apache-2.0
//
// `RevSugar`: the `.rev()` adaptor (and the synthetic final `Rev` appended for
// `.rfold`). A decorator `Sugar` over an inner sequence-`Sugar` that reverses the
// element sequence. Lifted verbatim from the `Adaptor::Rev` arm of the former
// `apply_one_adaptor` match.

use crate::{Desugared, Outcome, Sugar, SugarCtx};

/// Reverse the inner element sequence.
pub(crate) struct RevSugar {
    pub(crate) inner: Box<dyn Sugar>,
}

impl Sugar for RevSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
            let mut s = seq;
            s.reverse();
            Some(Desugared::Seq(s))
        })())
    }
}
