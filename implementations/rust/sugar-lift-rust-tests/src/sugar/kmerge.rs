// SPDX-License-Identifier: Apache-2.0
//
// `KMergeSugar`: itertools `.kmerge()` over a finite literal-derived sequence of
// finite literal-derived sub-sequences. Empty sub-sequences contribute no elements.
// Non-empty sub-sequences must expose exact integer values so the merged ordering is
// determined; otherwise the sugar declines rather than fabricating an order.

use std::collections::BTreeMap;

use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_composite, has_composite, SugarBuildCtx};
use crate::sugar::literal::EMPTY_DOMAIN_REASON;
use crate::{ConstVal, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("kmerge", SugarRole::Composite, recognize_composite);

fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "kmerge" || !call.args.is_empty() {
        return None;
    }
    if !has_composite(&call.receiver, fcx) {
        return None;
    }
    Some(Box::new(KMergeSugar {
        inner: (*call.receiver).clone(),
        let_inits: capture_let_inits(fcx),
    }))
}

struct KMergeSugar {
    inner: Expr,
    let_inits: BTreeMap<String, Expr>,
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

impl Sugar for KMergeSugar {
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
            let outer = build_composite(&self.inner, &fcx)
                .desugar(ctx)
                .dug()?
                .into_seq()?;
            let mut out = Vec::new();
            for elem in outer {
                let sub = match build_composite(&elem.expr, &fcx).desugar(ctx) {
                    Outcome::Dug(desugared) => desugared.into_seq()?,
                    Outcome::Hit(Effect::Unsupported { reason })
                        if reason == EMPTY_DOMAIN_REASON =>
                    {
                        Vec::new()
                    }
                    Outcome::Hit(_) => return None,
                };
                let total = out.len().checked_add(sub.len())?;
                if total as i64 > SUGAR_SEQ_CAP {
                    return None;
                }
                out.extend(sub);
            }
            if !out.is_empty() {
                let mut sortable = Vec::with_capacity(out.len());
                for elem in out {
                    let key = elem.value.as_ref().and_then(ConstVal::as_int)?;
                    sortable.push((key, elem));
                }
                sortable.sort_by_key(|(key, _)| *key);
                out = sortable
                    .into_iter()
                    .map(|(_, elem): (i128, DesugaredElem)| elem)
                    .collect();
            }
            debug!(
                target: "sugar_lift_rust_tests::sugar::kmerge",
                len = out.len(),
                "merged finite literal-derived iterator family"
            );
            Some(Desugared::Seq(out))
        })())
    }
}
