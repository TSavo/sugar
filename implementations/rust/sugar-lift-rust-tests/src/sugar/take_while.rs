// SPDX-License-Identifier: Apache-2.0
//
// `TakeWhileSugar`: the `.take_while(pred)` adaptor. A decorator `Sugar` over an
// inner sequence-`Sugar` that keeps the leading run of elements where the closure
// const-evaluates true. Bails (None) on an opaque element in the kept prefix or a
// non-bool / runtime closure result. Lifted verbatim from the
// `Adaptor::TakeWhile(closure)` arm of the former `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::method_family;
use crate::{const_eval_unary_closure, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("take_while", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "take_while" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(pred) = &call.args[0] else {
        return None;
    };
    Some(Box::new(TakeWhileSugar {
        inner: method_family::build_literal_sequence_composite(&call.receiver, fcx)?,
        pred: pred.clone(),
    }))
}

/// Keep the leading run of elements where `pred` const-evaluates true.
pub(crate) struct TakeWhileSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) pred: syn::ExprClosure,
}

impl Sugar for TakeWhileSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
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
        })())
    }
}
