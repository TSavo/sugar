// SPDX-License-Identifier: Apache-2.0
//
// `TakeSugar`: the `.take(n)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that keeps the first `n` elements. Lifted verbatim from the
// `Adaptor::Take(n)` arm of the former `apply_one_adaptor` match.

use crate::{Desugared, Outcome, Sugar, SugarCtx};

/// Keep the first `n` elements of the inner sequence.
pub(crate) struct TakeSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) n: usize,
}

impl Sugar for TakeSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
            let out = seq.into_iter().take(self.n).collect();
            Some(Desugared::Seq(out))
        })())
    }
}
