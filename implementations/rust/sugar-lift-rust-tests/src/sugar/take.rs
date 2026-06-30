// SPDX-License-Identifier: Apache-2.0
//
// `TakeSugar`: the `.take(n)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that keeps the first `n` elements. Lifted verbatim from the
// `Adaptor::Take(n)` arm of the former `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, DesugaredElem, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("take", recognize_composite);

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "take" || call.args.len() != 1 {
        return None;
    }
    let n = method_family::const_usize_in_build_ctx(&call.args[0], fcx)?;
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits())
        && !has_composite(&call.receiver, fcx)
    {
        return None;
    }
    let source = Expr::MethodCall(call.clone());
    Some(Box::new(TakeSugar {
        inner: SugarBody::composite(&call.receiver, fcx),
        n,
        finite_source: method_family::finite_int_iter_sequence_in_build_ctx(&source, fcx),
    }))
}

/// Keep the first `n` elements of the inner sequence.
pub(crate) struct TakeSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) n: usize,
    pub(crate) finite_source: Option<Vec<DesugaredElem>>,
}

impl Sugar for TakeSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.inner.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_seq()
                .or_else(|| self.finite_source.clone())
                .unwrap_or_else(|| take_gap("take receiver reduced to non-sequence")),
            Outcome::Incomplete(effect) => match self.finite_source.clone() {
                Some(seq) => seq,
                None => return Outcome::Incomplete(effect),
            },
        };
        let out = seq.into_iter().take(self.n).collect();
        Outcome::Complete(Desugared::Seq(out))
    }
}

fn take_gap(reason: &str) -> ! {
    panic!("take did not reach a lawful floor: {reason}")
}
