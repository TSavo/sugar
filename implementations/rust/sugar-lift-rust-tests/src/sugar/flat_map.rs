// SPDX-License-Identifier: Apache-2.0
//
// `flat_map`: the `.flat_map(|x| [..])` / `.flat_map(|&n| 0..n)` adaptor over a finite
// literal base whose closure maps each element to a finite literal SUB-SEQUENCE -- an
// array literal OR a bounded range literal (`a..b` / `a..=b`). It applies the closure to
// each element (const-eval, the SAME exact floor as `.map`) and concatenates the
// resulting sub-sequences in source order -- `map` + `flatten` in one step. This is the
// outermost-call recognizer; `peel_fold_adaptors` carries the same `FlatMapSugar` when
// `.flat_map(..)` sits inside a longer adaptor chain.
//
// EXACT-OR-REFUSE: an opaque element (no const value), a closure body that is neither an
// array literal nor a both-ends-bounded range, or any sub-element outside the certain
// const set bails (`None` -> refuse, NEVER a guessed sub-sequence) -- the same discipline
// as `map`/`flatten`. (A range whose start >= end yields the empty sub-sequence, a
// legitimate flat_map drop.)

use std::collections::BTreeMap;

use crate::sugar::factory::{has_composite, SugarBuildCtx};
use crate::sugar::method_family;
use crate::{
    const_eval_flat_map_closure, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP,
};
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("flat_map", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "flat_map" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(f) = &call.args[0] else {
        return None;
    };
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits())
        && !has_composite(&call.receiver, fcx)
    {
        return None;
    }
    Some(Box::new(FlatMapRecognizedSugar {
        receiver: (*call.receiver).clone(),
        f: f.clone(),
        let_inits: capture_let_inits(fcx),
    }))
}

struct FlatMapRecognizedSugar {
    receiver: Expr,
    f: syn::ExprClosure,
    let_inits: BTreeMap<String, Expr>,
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

impl Sugar for FlatMapRecognizedSugar {
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
            let mut out = Vec::new();
            for elem in seq {
                let value = elem.value.as_ref()?;
                let sub = const_eval_flat_map_closure(&self.f, value)?;
                let total = out.len().checked_add(sub.len())?;
                if total as i64 > SUGAR_SEQ_CAP {
                    return None;
                }
                for v in sub {
                    out.push(DesugaredElem {
                        expr: v.to_expr()?,
                        value: Some(v),
                    });
                }
            }
            Some(Desugared::Seq(out))
        })())
    }
}

/// Apply the closure to each element and concatenate the resulting finite literal
/// sub-sequences in source order.
pub(crate) struct FlatMapSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) f: syn::ExprClosure,
}

impl Sugar for FlatMapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
            let mut out = Vec::new();
            for elem in seq {
                // An opaque element (no const value) cannot drive the closure -> refuse.
                let value = elem.value.as_ref()?;
                let sub = const_eval_flat_map_closure(&self.f, value)?;
                let total = out.len().checked_add(sub.len())?;
                if total as i64 > SUGAR_SEQ_CAP {
                    return None;
                }
                for v in sub {
                    out.push(DesugaredElem {
                        expr: v.to_expr()?, // materialize for EUF translation
                        value: Some(v),
                    });
                }
            }
            Some(Desugared::Seq(out))
        })())
    }
}
