// SPDX-License-Identifier: Apache-2.0
//
// `flat_map`: the `.flat_map(|x| [..])` adaptor over a finite literal base whose closure
// maps each element to a finite literal SUB-SEQUENCE (an array literal). It applies the
// closure to each element (const-eval, the SAME exact floor as `.map`) and concatenates
// the resulting sub-sequences in source order -- `map` + `flatten` in one step. This is
// the outermost-call recognizer; `peel_fold_adaptors` carries the same `FlatMapSugar`
// when `.flat_map(..)` sits inside a longer adaptor chain.
//
// EXACT-OR-REFUSE: an opaque element (no const value), a closure body that is not an
// array literal, or any sub-element outside the certain const set bails (`None` ->
// refuse, NEVER a guessed sub-sequence) -- the same discipline as `map`/`flatten`.

use crate::sugar::factory::{build_composite, SugarBuildCtx};
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
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits()) {
        return None;
    }
    Some(Box::new(FlatMapSugar {
        inner: build_composite(&call.receiver, fcx),
        f: f.clone(),
    }))
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
