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
// EXACT-OR-REFUSE: an opaque element (no const value), an unbounded literal range, a
// runtime literal-domain bound, or an over-cap finite domain refuses with a named
// terminal literal-domain reason. Shapes the evaluator does not own are gaps and must
// stay loud. A range whose start >= end yields the empty sub-sequence, a legitimate
// flat_map drop.

use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::{
    const_eval_flat_map_closure, ConstVal, Desugared, DesugaredElem, Effect, FlatMapClosureEval,
    Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP,
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
        inner: SugarBody::composite(&call.receiver, fcx),
        mapper: FlatMapClosure::new(f.clone()),
    }))
}

struct FlatMapRecognizedSugar {
    inner: SugarBody<CompositeFloor>,
    mapper: FlatMapClosure,
}

impl Sugar for FlatMapRecognizedSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_flat_map(&self.inner, &self.mapper, ctx)
    }
}

pub(crate) struct FlatMapClosure {
    expr: syn::ExprClosure,
}

impl FlatMapClosure {
    pub(crate) fn new(expr: syn::ExprClosure) -> Self {
        Self { expr }
    }

    fn eval(&self, value: &ConstVal) -> FlatMapClosureEval {
        const_eval_flat_map_closure(&self.expr, value)
    }
}

/// Apply the closure to each element and concatenate the resulting finite literal
/// sub-sequences in source order.
pub(crate) struct FlatMapSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) mapper: FlatMapClosure,
}

impl Sugar for FlatMapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_flat_map(&self.inner, &self.mapper, ctx)
    }
}

fn reduce_flat_map(
    inner: &SugarBody<CompositeFloor>,
    mapper: &FlatMapClosure,
    ctx: &SugarCtx,
) -> Outcome {
    let seq = match inner.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_seq()
            .unwrap_or_else(|| flat_map_gap("flat_map receiver reduced to non-sequence")),
        Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
    };
    let mut out = Vec::new();
    for elem in seq {
        // An opaque element (no const value) cannot drive the closure.
        let Some(value) = elem.value.as_ref() else {
            return flat_map_literal_domain(
                "literal array element is not text-determined -- flat_map input element is not constructible from source literals; refused",
            );
        };
        let sub = match mapper.eval(value) {
            FlatMapClosureEval::Finite(sub) => sub,
            FlatMapClosureEval::LiteralDomain(reason) => return flat_map_literal_domain(reason),
            FlatMapClosureEval::Gap => {
                flat_map_gap("flat_map closure did not reduce to a finite sequence")
            }
        };
        let Some(total) = out.len().checked_add(sub.len()) else {
            flat_map_gap("flat_map literal sequence length overflowed");
        };
        if total > SUGAR_SEQ_CAP as usize {
            return flat_map_literal_domain(
                "literal domain exceeds SUGAR_SEQ_CAP -- flat_map concatenated sequence is finite but over-cap; refused",
            );
        }
        for v in sub {
            out.push(DesugaredElem {
                expr: v
                    .to_expr()
                    .unwrap_or_else(|| flat_map_gap("flat_map result could not materialize")),
                value: Some(v),
            });
        }
    }
    Outcome::Complete(Desugared::Seq(out))
}

fn flat_map_gap(reason: &str) -> ! {
    panic!("flat_map did not reach a lawful floor: {reason}")
}

fn flat_map_literal_domain(reason: &str) -> Outcome {
    Outcome::Incomplete(Effect::LiteralDomain {
        boundary: "flat_map".to_string(),
        reason: reason.to_string(),
    })
}
