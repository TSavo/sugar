// SPDX-License-Identifier: Apache-2.0
//
// `StepBySugar`: the `.step_by(n)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that keeps every `n`-th element starting at index 0
// (`[1, 2, 3, 4, 5].step_by(2)` -> `1, 3, 5`). EXACT-OR-REFUSE: only a const
// integer `n >= 1` over a finite literal sequence; `step_by(0)` is a Rust panic, so
// it refuses (`None`) rather than guess. Mirrors `SkipSugar`/`TakeSugar`.

use std::collections::BTreeMap;

use syn::Expr;

use crate::sugar::factory::{has_composite, SugarBuildCtx};
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
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits())
        && !has_composite(&call.receiver, fcx)
    {
        return None;
    }
    Some(Box::new(StepByRecognizedSugar {
        receiver: (*call.receiver).clone(),
        source: Expr::MethodCall(call.clone()),
        n,
        let_inits: capture_let_inits(fcx),
    }))
}

struct StepByRecognizedSugar {
    receiver: Expr,
    source: Expr,
    n: usize,
    let_inits: BTreeMap<String, Expr>,
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

impl Sugar for StepByRecognizedSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            if self.n == 0 {
                return None;
            }
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
                .dug()
                .and_then(|d| d.into_seq())
                .or_else(|| method_family::finite_int_iter_sequence(&self.source))?;
            let out = seq.into_iter().step_by(self.n).collect();
            Some(Desugared::Seq(out))
        })())
    }
}

/// Keep every `n`-th element of the inner sequence, starting at index 0.
pub(crate) struct StepBySugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) n: usize,
    pub(crate) source: Option<Expr>,
}

impl Sugar for StepBySugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            if self.n == 0 {
                return None;
            }
            let seq = self
                .inner
                .desugar(ctx)
                .dug()
                .and_then(|d| d.into_seq())
                .or_else(|| {
                    self.source
                        .as_ref()
                        .and_then(method_family::finite_int_iter_sequence)
                })?;
            let out = seq.into_iter().step_by(self.n).collect();
            Some(Desugared::Seq(out))
        })())
    }
}
