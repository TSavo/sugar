// SPDX-License-Identifier: Apache-2.0
//
// `IdentitySugar`: the `iter` / `into_iter` / `cloned` / `copied` / `fuse` adaptor.
// A decorator `Sugar` over an inner sequence-`Sugar` whose `desugar` is the identity
// over the element sequence -- it passes the inner sequence through unchanged. Lifted
// verbatim from the `Adaptor::Identity` arm of the former `apply_one_adaptor` match.

use crate::{Desugared, Outcome, Sugar, SugarCtx};

/// `iter` / `into_iter` / `cloned` / `copied` / `fuse`: pass the inner element
/// sequence through unchanged.
pub(crate) struct IdentitySugar {
    pub(crate) inner: Box<dyn Sugar>,
}

impl Sugar for IdentitySugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).complete()?.into_seq()?;
            Some(Desugared::Seq(seq))
        })())
    }
}
