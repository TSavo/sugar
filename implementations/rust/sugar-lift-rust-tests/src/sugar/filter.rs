// SPDX-License-Identifier: Apache-2.0
//
// `FilterSugar`: the `.filter(pred)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that keeps the elements where the closure const-evaluates true.
// Bails (None) on an opaque element (no const value) or a non-bool / runtime
// closure result. Lifted verbatim from the `Adaptor::Filter(closure)` arm of the
// former `apply_one_adaptor` match.

use crate::{const_eval_unary_closure, Desugared, Sugar, SugarCtx};

/// Keep the elements where `pred` const-evaluates true.
pub(crate) struct FilterSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) pred: syn::ExprClosure,
}

impl Sugar for FilterSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Option<Desugared> {
        let seq = self.inner.desugar(ctx)?.into_seq()?;
        let mut out = Vec::new();
        for elem in seq {
            let v = elem.value.as_ref()?; // opaque element under a filter -> bail
            if const_eval_unary_closure(&self.pred, v)?.as_bool()? {
                out.push(elem);
            }
        }
        Some(Desugared::Seq(out))
    }
}
