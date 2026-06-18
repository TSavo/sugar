// SPDX-License-Identifier: Apache-2.0
//
// `RevSugar`: the `.rev()` adaptor (and the synthetic final `Rev` appended for
// `.rfold`). A decorator `Sugar` over an inner sequence-`Sugar` that reverses the
// element sequence. Lifted verbatim from the `Adaptor::Rev` arm of the former
// `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::factory::{build_composite, FactoryCtx};
use crate::sugar::method_family;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("rev", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method == "rev"
        && call.args.is_empty()
        && method_family::resolves_literal_sequence(expr, fcx.let_inits)
    {
        return Some(Box::new(RevSugar {
            inner: build_composite(&call.receiver, fcx),
        }));
    }
    None
}

/// Reverse the inner element sequence.
pub(crate) struct RevSugar {
    pub(crate) inner: Box<dyn Sugar>,
}

impl Sugar for RevSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
            let mut s = seq;
            s.reverse();
            Some(Desugared::Seq(s))
        })())
    }
}
