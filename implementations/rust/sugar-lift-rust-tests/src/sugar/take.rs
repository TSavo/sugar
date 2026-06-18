// SPDX-License-Identifier: Apache-2.0
//
// `TakeSugar`: the `.take(n)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that keeps the first `n` elements. Lifted verbatim from the
// `Adaptor::Take(n)` arm of the former `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::factory::{build_composite, SugarBuildCtx};
use crate::sugar::method_family;
use crate::{const_int, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("take", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "take" || call.args.len() != 1 {
        return None;
    }
    let n: usize = const_int(&call.args[0])?.try_into().ok()?;
    if !method_family::resolves_literal_sequence(expr, fcx.let_inits()) {
        return None;
    }
    Some(Box::new(TakeSugar {
        inner: build_composite(&call.receiver, fcx),
        n,
    }))
}

/// Keep the first `n` elements of the inner sequence.
pub(crate) struct TakeSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) n: usize,
}

impl Sugar for TakeSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
            let out = seq.into_iter().take(self.n).collect();
            Some(Desugared::Seq(out))
        })())
    }
}
