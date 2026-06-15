// SPDX-License-Identifier: Apache-2.0
//
// `MapSugar`: the `.map(f)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that replaces each element with the closure's const value. Bails
// (None) on an opaque element (no const value), a runtime/overflowing closure, or a
// mapped value it cannot materialize back to an `Expr`. Lifted verbatim from the
// `Adaptor::Map(closure)` arm of the former `apply_one_adaptor` match.

use crate::{const_eval_unary_closure, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx};

/// Replace each element with the const value of `f` applied to it.
pub(crate) struct MapSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) f: syn::ExprClosure,
}

impl Sugar for MapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
            let mut out = Vec::with_capacity(seq.len());
            for elem in seq {
                let v = elem.value.as_ref()?; // opaque element under a map -> bail
                let mapped = const_eval_unary_closure(&self.f, v)?;
                let mexpr = mapped.to_expr()?; // materialize for EUF translation
                out.push(DesugaredElem {
                    expr: mexpr,
                    value: Some(mapped),
                });
            }
            Some(Desugared::Seq(out))
        })())
    }
}
