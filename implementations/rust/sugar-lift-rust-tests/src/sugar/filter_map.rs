// SPDX-License-Identifier: Apache-2.0
//
// `FilterMapSugar`: the `.filter_map(f)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that const-evaluates the `Option`-returning closure over each
// element and keeps the `Some(v)` values (dropping the `None`s). The composable
// mirror of the `filter_map` arm already proven diggable in the closed `try_fold`
// value-evaluator (`try_fold_eval::eval_seq_chain`): SAME `const_eval` floor, SAME
// `Some`/`None` Option-shape, now wired as a decorator so a `filter_map` feeding a
// `fold`/`rfold`/`for_each`/for-loop terminal digs through the ordinary `Sugar` tree.
// Bails (None) on an opaque element (no const value), a non-`Option` / runtime closure
// result, or a kept value it cannot materialize back to an `Expr` -- exact-or-bail,
// same as `MapSugar` / `FilterSugar`.

use syn::Expr;

use crate::sugar::factory::{build_composite, FactoryCtx};
use crate::{const_eval_option_closure, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("filter_map", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "filter_map" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(f) = &call.args[0] else {
        return None;
    };
    Some(Box::new(FilterMapSugar {
        inner: build_composite(&call.receiver, fcx),
        f: f.clone(),
    }))
}

/// Const-evaluate `f` (returning `Option`) over each element and keep the `Some` values.
pub(crate) struct FilterMapSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) f: syn::ExprClosure,
}

impl Sugar for FilterMapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.inner.desugar(ctx).dug()?.into_seq()?;
            let mut out = Vec::with_capacity(seq.len());
            for elem in seq {
                let v = elem.value.as_ref()?; // opaque element under a filter_map -> bail
                                              // The closure returns `Option<_>`: a `None` drops the element, a
                                              // `Some(v)` keeps it with its mapped const value. A non-`Option` /
                                              // runtime / unmodeled body bails the whole defold.
                if let Some(mapped) = const_eval_option_closure(&self.f, v)? {
                    let mexpr = mapped.to_expr()?; // materialize for EUF translation
                    out.push(DesugaredElem {
                        expr: mexpr,
                        value: Some(mapped),
                    });
                }
            }
            Some(Desugared::Seq(out))
        })())
    }
}
