// SPDX-License-Identifier: Apache-2.0
//
// `FilterMapSugar`: the `.filter_map(f)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that const-evaluates the `Option`-returning closure over each
// element and keeps the `Some(v)` values (dropping the `None`s). The composable
// `filter_map` arm uses the same `const_eval` floor and `Some`/`None` Option-shape as
// the other iterator sugars, wired as a decorator so a `filter_map` feeding a
// `fold`/`rfold`/`for_each`/for-loop terminal completes through the ordinary `Sugar` tree.
// Bails (None) on an opaque element (no const value), a non-`Option` / runtime closure
// result, or a kept value it cannot materialize back to an `Expr` -- exact-or-bail,
// same as `MapSugar` / `FilterSugar`.

use syn::Expr;

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::{
    const_eval_option_closure, ConstVal, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx,
};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("filter_map", recognize_composite);

pub(crate) fn recognize_composite(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
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
        inner: SugarBody::from_node(method_family::build_literal_sequence_composite(
            &call.receiver,
            fcx,
        )?),
        mapper: FilterMapClosure::new(f.clone()),
    }))
}

pub(crate) struct FilterMapClosure {
    expr: syn::ExprClosure,
}

impl FilterMapClosure {
    pub(crate) fn new(expr: syn::ExprClosure) -> Self {
        Self { expr }
    }

    fn eval(&self, value: &ConstVal) -> Option<Option<ConstVal>> {
        const_eval_option_closure(&self.expr, value)
    }
}

/// Const-evaluate `f` (returning `Option`) over each element and keep the `Some` values.
pub(crate) struct FilterMapSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) mapper: FilterMapClosure,
}

impl Sugar for FilterMapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.inner.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_seq()
                .unwrap_or_else(|| filter_map_gap("filter_map receiver reduced to non-sequence")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let mut out = Vec::with_capacity(seq.len());
        for elem in seq {
            let v = elem
                .value
                .as_ref()
                .unwrap_or_else(|| filter_map_gap("filter_map element was not literal"));
            // The closure returns `Option<_>`: a `None` drops the element, a
            // `Some(v)` keeps it with its mapped const value. A non-`Option` /
            // runtime / unmodeled body is a gap, not a fake effect.
            if let Some(mapped) = self
                .mapper
                .eval(v)
                .unwrap_or_else(|| filter_map_gap("filter_map closure did not reduce to Option"))
            {
                let mexpr = mapped
                    .to_expr()
                    .unwrap_or_else(|| filter_map_gap("filter_map result could not materialize"));
                out.push(DesugaredElem {
                    expr: mexpr,
                    value: Some(mapped),
                });
            }
        }
        Outcome::Complete(Desugared::Seq(out))
    }
}

fn filter_map_gap(reason: &str) -> ! {
    panic!("filter_map did not reach a lawful floor: {reason}")
}
