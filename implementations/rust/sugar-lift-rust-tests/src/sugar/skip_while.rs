// SPDX-License-Identifier: Apache-2.0
//
// `SkipWhileSugar`: the `.skip_while(pred)` adaptor. A decorator `Sugar` over an
// inner sequence-`Sugar` that drops the leading run of elements where the closure
// const-evaluates true. Bails (None) on an opaque element in the skipped prefix or
// a non-bool / runtime closure result. Lifted verbatim from the
// `Adaptor::SkipWhile(closure)` arm of the former `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::factory::{build_composite, FactoryCtx};
use crate::sugar::method_family;
use crate::{const_eval_unary_closure, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("skip_while", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "skip_while" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(pred) = &call.args[0] else {
        return None;
    };
    if !method_family::resolves_literal_sequence(expr, fcx.let_inits) {
        return None;
    }
    Some(Box::new(SkipWhileSugar {
        inner: build_composite(&call.receiver, fcx),
        pred: pred.clone(),
    }))
}

/// Drop the leading run of elements where `pred` const-evaluates true.
pub(crate) struct SkipWhileSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) pred: syn::ExprClosure,
}

impl Sugar for SkipWhileSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
            let mut out = Vec::new();
            let mut still_skipping = true;
            for elem in seq {
                if still_skipping {
                    let v = elem.value.as_ref()?;
                    if const_eval_unary_closure(&self.pred, v)?.as_bool()? {
                        continue;
                    }
                    still_skipping = false;
                }
                out.push(elem);
            }
            Some(Desugared::Seq(out))
        })())
    }
}
