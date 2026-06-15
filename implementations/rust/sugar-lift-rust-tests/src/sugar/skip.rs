// SPDX-License-Identifier: Apache-2.0
//
// `SkipSugar`: the `.skip(n)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that drops the first `n` elements. Lifted verbatim from the
// `Adaptor::Skip(n)` arm of the former `apply_one_adaptor` match.

use crate::{Desugared, Sugar, SugarCtx};

/// Drop the first `n` elements of the inner sequence.
pub(crate) struct SkipSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) n: usize,
}

impl Sugar for SkipSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Option<Desugared> {
        let seq = self.inner.desugar(ctx)?.into_seq()?;
        let out = seq.into_iter().skip(self.n).collect();
        Some(Desugared::Seq(out))
    }
}
