// SPDX-License-Identifier: Apache-2.0
//
// `MapSugar`: the `.map(f)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that replaces each element with the closure's const value. Bails
// (None) on an opaque element (no const value), a runtime/overflowing closure, or a
// mapped value it cannot materialize back to an `Expr`. Lifted verbatim from the
// `Adaptor::Map(closure)` arm of the former `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::factory::{build_composite, FactoryCtx};
use crate::{const_eval_unary_closure, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("map", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "map" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(f) = &call.args[0] else {
        return None;
    };
    Some(Box::new(MapSugar {
        inner: build_composite(&call.receiver, fcx),
        f: f.clone(),
    }))
}

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
