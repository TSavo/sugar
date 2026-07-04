// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `IdentitySugar`: the `iter` / `into_iter` / `cloned` / `copied` / `fuse` adaptor.
// A decorator `Sugar` over an inner sequence-`Sugar` whose `desugar` is the identity
// over the element sequence -- it passes the inner sequence through unchanged. Lifted
// verbatim from the `Adaptor::Identity` arm of the former `apply_one_adaptor` match.

use crate::sugar::factory::{CompositeFloor, SugarBody};
use crate::{Outcome, Sugar, SugarCtx};

/// `iter` / `into_iter` / `cloned` / `copied` / `fuse`: pass the inner element
/// sequence through unchanged.
pub(crate) struct IdentitySugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
}

impl Sugar for IdentitySugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.inner.reduce(ctx) {
            Outcome::Complete(d @ (crate::Desugared::Seq(_) | crate::Desugared::TermSeq(_))) => {
                Outcome::Complete(d)
            }
            Outcome::Complete(_) => identity_gap("inner reduced to non-sequence"),
            Outcome::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}

fn identity_gap(reason: &str) -> ! {
    panic!("identity did not reach a lawful floor: {reason}")
}
