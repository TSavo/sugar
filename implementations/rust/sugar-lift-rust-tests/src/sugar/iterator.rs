// SPDX-License-Identifier: Apache-2.0
//
// `IteratorSugar`: the `.iter()` / `.into_iter()` identity-family adaptor over a
// sequence Sugar. It is the explicit node between a literal domain and terminals like
// `.next()`: `[1, 2, 3]` -> `LiteralSugar`, `.iter()` -> `IteratorSugar`, `.next()` ->
// `IterTerminalSugar`. Recognition claims only receivers that are already literal-resolvable
// through the Composite/literal-sequence factory gates; unknown runtime-looking receivers stay
// structural factory holes instead of being laundered into a named runtime verdict.

use std::collections::BTreeMap;

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::method_family;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("iterator", recognize_composite);

/// COMPOSITE recognizer for identity-family iterator adaptors.
pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !call.args.is_empty() {
        return None;
    }
    match call.method.to_string().as_str() {
        "iter" | "into_iter" | "cloned" | "copied" | "fuse" | "by_ref" => {
            method_family::build_literal_sequence_composite(&call.receiver, fcx)?;
            Some(Box::new(IteratorSugar {
                receiver: (*call.receiver).clone(),
                let_inits: capture_let_inits(fcx),
            }))
        }
        _ => None,
    }
}

/// Identity-family iterator adaptor. Desugars by passing through the inner sequence.
pub(crate) struct IteratorSugar {
    pub(crate) receiver: Expr,
    pub(crate) let_inits: BTreeMap<String, Expr>,
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

impl Sugar for IteratorSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
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
        let Some(inner) = method_family::build_literal_sequence_composite(&self.receiver, &fcx)
        else {
            return Outcome::from_opt(None);
        };
        match inner.desugar(ctx) {
            Outcome::Complete(desugared) => match desugared.into_seq() {
                Some(seq) => Outcome::Complete(Desugared::Seq(seq)),
                None => Outcome::from_opt(None),
            },
            Outcome::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}
