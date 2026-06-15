// SPDX-License-Identifier: Apache-2.0
//
// `TakeWhileSugar`: the `.take_while(pred)` adaptor. A decorator `Sugar` over an
// inner sequence-`Sugar` that keeps the leading run of elements where the closure
// const-evaluates true. Bails (None) on an opaque element in the kept prefix or a
// non-bool / runtime closure result. Lifted verbatim from the
// `Adaptor::TakeWhile(closure)` arm of the former `apply_one_adaptor` match.

use crate::{const_eval_unary_closure, Desugared, Sugar, SugarCtx};

/// Keep the leading run of elements where `pred` const-evaluates true.
pub(crate) struct TakeWhileSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) pred: syn::ExprClosure,
}

impl Sugar for TakeWhileSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Option<Desugared> {
        let seq = self.inner.desugar(ctx)?.into_seq()?;
        let mut out = Vec::new();
        for elem in seq {
            let v = elem.value.as_ref()?;
            if const_eval_unary_closure(&self.pred, v)?.as_bool()? {
                out.push(elem);
            } else {
                break;
            }
        }
        Some(Desugared::Seq(out))
    }
}
