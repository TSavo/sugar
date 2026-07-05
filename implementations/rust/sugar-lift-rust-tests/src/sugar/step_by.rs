// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `StepBySugar`: the `.step_by(n)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that keeps every `n`-th element starting at index 0
// (`[1, 2, 3, 4, 5].step_by(2)` -> `1, 3, 5`). EXACT-OR-REFUSE: only a const
// integer `n >= 1` over a finite literal sequence; `step_by(0)` is a Rust panic, so
// it refuses (`None`) rather than guess. Mirrors `SkipSugar`/`TakeSugar`.

use syn::Expr;

use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::literal::EMPTY_DOMAIN_REASON;
use crate::sugar::method_family;
use crate::sugar::source_fragment::SourceFragment;
use crate::{const_int, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "step_by",
        crate::sugar::claim::SugarWitnesses::temporal_campaign(
            "S5 adapter family: step_by standing",
        ),
        recognize_composite,
    );

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "step_by" || call.args.len() != 1 {
        return None;
    }
    let n: usize = const_int(&call.args[0])?.try_into().ok()?;
    // `step_by(0)` panics at runtime; never invent a value for it.
    if n == 0 {
        return None;
    }
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits())
        && !has_composite(&call.receiver, fcx)
    {
        return None;
    }
    let source = Expr::MethodCall(call.clone());
    Some(Box::new(StepBySugar {
        inner: SugarBody::composite(&call.receiver, fcx),
        n,
        finite_source: method_family::finite_int_iter_sequence(&source),
    }))
}

/// Keep every `n`-th element of the inner sequence, starting at index 0.
pub(crate) struct StepBySugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) n: usize,
    pub(crate) finite_source: Option<Vec<DesugaredElem>>,
}

impl Sugar for StepBySugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if self.n == 0 {
            step_by_gap("step_by(0) should be rejected at construction");
        }
        let seq = match seq_or_empty(self.inner.reduce(ctx)) {
            Ok(Some(seq)) => seq,
            Ok(None) => match self.finite_source.clone() {
                Some(seq) => seq,
                None => step_by_gap("step_by receiver reduced to non-sequence"),
            },
            Err(outcome) => match self.finite_source.clone() {
                Some(seq) => seq,
                None => return outcome,
            },
        };
        let out = seq.into_iter().step_by(self.n).collect();
        Outcome::Complete(Desugared::Seq(out))
    }
}

fn seq_or_empty(outcome: Outcome) -> Result<Option<Vec<DesugaredElem>>, Outcome> {
    match outcome {
        Outcome::Complete(d) => Ok(d.into_seq()),
        Outcome::Incomplete(effect) if effect.is_literal_domain_reason(EMPTY_DOMAIN_REASON) => {
            Ok(Some(Vec::new()))
        }
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn step_by_gap(reason: &str) -> ! {
    panic!("step_by did not reach a lawful sequence floor: {reason}")
}
