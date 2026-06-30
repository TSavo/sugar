// SPDX-License-Identifier: Apache-2.0
//
// `FilterSugar`: the `.filter(pred)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that keeps the elements where the closure const-evaluates true.
// Bails (None) on an opaque element (no const value) or a non-bool / runtime
// closure result. Lifted verbatim from the `Adaptor::Filter(closure)` arm of the
// former `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::bool_predicate::BoolPredicateClosure;
use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::{Desugared, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("filter", recognize_composite);

pub(crate) fn recognize_composite(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "filter" || call.args.len() != 1 {
        return None;
    }
    let Expr::Closure(pred) = &call.args[0] else {
        return None;
    };
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits())
        && !has_composite(&call.receiver, fcx)
    {
        return None;
    }
    Some(Box::new(FilterRecognizedSugar {
        inner: SugarBody::composite(&call.receiver, fcx),
        pred: BoolPredicateClosure::build(pred.clone(), fcx)?,
    }))
}

struct FilterRecognizedSugar {
    inner: SugarBody<CompositeFloor>,
    pred: BoolPredicateClosure,
}

impl Sugar for FilterRecognizedSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_filter(&self.inner, &self.pred, ctx)
    }
}

/// Keep the elements where `pred` const-evaluates true.
pub(crate) struct FilterSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) pred: BoolPredicateClosure,
}

impl Sugar for FilterSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_filter(&self.inner, &self.pred, ctx)
    }
}

fn reduce_filter(
    inner: &SugarBody<CompositeFloor>,
    pred: &BoolPredicateClosure,
    ctx: &SugarCtx,
) -> Outcome {
    let seq = match inner.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_seq()
            .unwrap_or_else(|| filter_gap("filter receiver reduced to non-sequence")),
        Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
    };
    let mut out = Vec::new();
    for (idx, elem) in seq.into_iter().enumerate() {
        let keep = match pred.eval_for_elem(&elem, idx, "filter", ctx) {
            Ok(keep) => keep,
            Err(outcome) => return outcome,
        };
        if keep {
            out.push(elem);
        }
    }
    Outcome::Complete(Desugared::Seq(out))
}

fn filter_gap(reason: &str) -> ! {
    panic!("filter did not reach a lawful floor: {reason}")
}
