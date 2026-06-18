// SPDX-License-Identifier: Apache-2.0
//
// `SkipSugar`: the `.skip(n)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that drops the first `n` elements. Lifted verbatim from the
// `Adaptor::Skip(n)` arm of the former `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::factory::{build_composite, FactoryCtx};
use crate::{const_int, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("skip", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "skip" || call.args.len() != 1 {
        return None;
    }
    let n: usize = const_int(&call.args[0])?.try_into().ok()?;
    Some(Box::new(SkipSugar {
        inner: build_composite(&call.receiver, fcx),
        n,
    }))
}

/// Drop the first `n` elements of the inner sequence.
pub(crate) struct SkipSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) n: usize,
}

impl Sugar for SkipSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
            let out = seq.into_iter().skip(self.n).collect();
            Some(Desugared::Seq(out))
        })())
    }
}
