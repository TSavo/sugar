// SPDX-License-Identifier: Apache-2.0
//
// `StepBySugar`: the `.step_by(n)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that keeps every `n`-th element starting at index 0
// (`[1, 2, 3, 4, 5].step_by(2)` -> `1, 3, 5`). EXACT-OR-REFUSE: only a const
// integer `n >= 1` over a finite literal sequence; `step_by(0)` is a Rust panic, so
// it refuses (`None`) rather than guess. Mirrors `SkipSugar`/`TakeSugar`.

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::method_family;
use crate::{const_int, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("step_by", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
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
    Some(Box::new(StepBySugar {
        inner: method_family::build_literal_sequence_composite(&call.receiver, fcx)?,
        n,
    }))
}

/// Keep every `n`-th element of the inner sequence, starting at index 0.
pub(crate) struct StepBySugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) n: usize,
}

impl Sugar for StepBySugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            if self.n == 0 {
                return None;
            }
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
            let out = seq.into_iter().step_by(self.n).collect();
            Some(Desugared::Seq(out))
        })())
    }
}
