// SPDX-License-Identifier: Apache-2.0
//
// `RevSugar`: the `.rev()` adaptor (and the synthetic final `Rev` appended for
// `.rfold`). A decorator `Sugar` over an inner sequence-`Sugar` that reverses the
// element sequence. Lifted verbatim from the `Adaptor::Rev` arm of the former
// `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::literal::EMPTY_DOMAIN_REASON;
use crate::sugar::method_family;
use crate::{Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("rev", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method == "rev" && call.args.is_empty() {
        let inner = method_family::build_literal_sequence_composite(&call.receiver, fcx)?;
        return Some(Box::new(RevSugar { inner }));
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
            let seq = seq_or_empty(self.inner.desugar(ctx))?;
            let mut s = seq;
            s.reverse();
            Some(Desugared::Seq(s))
        })())
    }
}

fn seq_or_empty(outcome: Outcome) -> Option<Vec<DesugaredElem>> {
    match outcome {
        Outcome::Dug(d) => d.into_seq(),
        Outcome::Hit(Effect::Unsupported { reason }) if reason == EMPTY_DOMAIN_REASON => {
            Some(Vec::new())
        }
        Outcome::Hit(_) => None,
    }
}
