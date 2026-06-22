// SPDX-License-Identifier: Apache-2.0
//
// `FilterSugar`: the `.filter(pred)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that keeps the elements where the closure const-evaluates true.
// Bails (None) on an opaque element (no const value) or a non-bool / runtime
// closure result. Lifted verbatim from the `Adaptor::Filter(closure)` arm of the
// former `apply_one_adaptor` match.

use std::collections::BTreeMap;

use syn::Expr;

use crate::sugar::factory::{has_composite, SugarBuildCtx};
use crate::sugar::method_family;
use crate::{const_eval_unary_closure, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("filter", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "filter" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(pred) = &call.args[0] else {
        return None;
    };
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits())
        && !has_composite(&call.receiver, fcx)
    {
        return None;
    }
    Some(Box::new(FilterRecognizedSugar {
        receiver: (*call.receiver).clone(),
        pred: pred.clone(),
        let_inits: capture_let_inits(fcx),
    }))
}

struct FilterRecognizedSugar {
    receiver: Expr,
    pred: syn::ExprClosure,
    let_inits: BTreeMap<String, Expr>,
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

impl Sugar for FilterRecognizedSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
            let let_inits: BTreeMap<String, &Expr> = stable
                .iter()
                .map(|(name, init)| (name.clone(), init))
                .chain(
                    self.let_inits
                        .iter()
                        .map(|(name, init)| (name.clone(), init)),
                )
                .collect();
            let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
            let seq = method_family::build_literal_sequence_composite(&self.receiver, &fcx)?
                .desugar(ctx)
                .dug()?
                .into_seq()?;
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
