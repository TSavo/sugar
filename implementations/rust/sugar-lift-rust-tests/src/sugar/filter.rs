// SPDX-License-Identifier: Apache-2.0
//
// `FilterSugar`: the `.filter(pred)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that keeps the elements where the closure const-evaluates true.
// Bails (None) on an opaque element (no const value) or a non-bool / runtime
// closure result. Lifted verbatim from the `Adaptor::Filter(closure)` arm of the
// former `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::factory::{build_composite, FactoryCtx};
use crate::sugar::method_family;
use crate::{const_eval_unary_closure, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("filter", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "filter" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(pred) = &call.args[0] else {
        return None;
    };
    if !method_family::resolves_literal_sequence(expr, fcx.let_inits) {
        return None;
    }
    Some(Box::new(FilterSugar {
        inner: build_composite(&call.receiver, fcx),
        pred: pred.clone(),
    }))
}

/// Keep the elements where `pred` const-evaluates true.
pub(crate) struct FilterSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) pred: syn::ExprClosure,
}

impl Sugar for FilterSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
            let mut out = Vec::new();
            for elem in seq {
                let v = elem.value.as_ref()?; // opaque element under a filter -> bail
                if const_eval_unary_closure(&self.pred, v)?.as_bool()? {
                    out.push(elem);
                }
            }
            Some(Desugared::Seq(out))
        })())
    }
}
