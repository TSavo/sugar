// SPDX-License-Identifier: Apache-2.0
//
// `TakeSugar`: the `.take(n)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that keeps the first `n` elements. Lifted verbatim from the
// `Adaptor::Take(n)` arm of the former `apply_one_adaptor` match.

use std::collections::BTreeMap;

use syn::Expr;

use crate::sugar::factory::{has_composite, SugarBuildCtx};
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
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits())
        && !has_composite(&call.receiver, fcx)
    {
        return None;
    }
    Some(Box::new(TakeRecognizedSugar {
        receiver: (*call.receiver).clone(),
        n,
        let_inits: capture_let_inits(fcx),
    }))
}

struct TakeRecognizedSugar {
    receiver: Expr,
    n: usize,
    let_inits: BTreeMap<String, Expr>,
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

impl Sugar for TakeRecognizedSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
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
                .dug()?
                .into_seq()?;
            let out = seq.into_iter().take(self.n).collect();
            Some(Desugared::Seq(out))
        })())
    }
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
