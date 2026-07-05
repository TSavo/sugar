// SPDX-License-Identifier: MIT OR Apache-2.0
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
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::temporal_floor::{
    AdapterFloorOutput, AdapterOutputIterMember, CountedAdapterFloor, IterStanding,
    TemporalFloorRefusal,
};
use crate::{Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "filter",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_filter_good() {
                    let got = [1i32, 2, 3, 4].into_iter().filter(|x| *x % 2 == 0).count();
                    assert_eq!(got, 2);
                }
            "#,
            r#"
                #[test]
                fn t_filter_bad() {
                    let got = [1i32, 2, 3, 4].into_iter().filter(|x| *x % 2 == 0).count();
                    assert_eq!(got, 3);
                }
            "#,
        ),
        recognize_composite,
    );

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
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
    let floor = FilterFloor::default();
    let operand = match floor.derived_operand(seq.len()) {
        Ok(operand) => operand,
        Err(outcome) => return outcome,
    };
    let output = match floor.desugar(operand, seq, |idx, elem| {
        pred.eval_for_elem(elem, idx, "filter", ctx)
    }) {
        Ok(output) => output,
        Err(outcome) => return outcome,
    };
    ctx.record_adapter_floor_audit("filter", output.standing().count());
    Outcome::Complete(Desugared::Seq(output.into_items()))
}

fn filter_gap(reason: &str) -> ! {
    panic!("filter did not reach a lawful floor: {reason}")
}

#[derive(Clone, Copy)]
struct FilterFloor {
    counted: CountedAdapterFloor,
}

impl Default for FilterFloor {
    fn default() -> Self {
        Self {
            counted: CountedAdapterFloor::new("filter", AdapterOutputIterMember::filter),
        }
    }
}

impl FilterFloor {
    fn derived_operand(&self, count: usize) -> Result<IterStanding, Outcome> {
        self.counted
            .derived_operand(count)
            .map_err(filter_floor_refusal)
    }

    fn desugar<F>(
        &self,
        operand: IterStanding,
        seq: Vec<DesugaredElem>,
        mut predicate: F,
    ) -> Result<AdapterFloorOutput<DesugaredElem>, Outcome>
    where
        F: FnMut(usize, &DesugaredElem) -> Result<bool, Outcome>,
    {
        let visited = seq.len();
        let measured = seq
            .into_iter()
            .enumerate()
            .map(|(idx, elem)| predicate(idx, &elem).map(|keep| (elem, keep)))
            .collect::<Result<Vec<_>, _>>()?;
        self.counted
            .assert_input_count(&operand, visited)
            .map_err(filter_floor_refusal)?;
        let kept = measured
            .into_iter()
            .filter(|(_, keep)| *keep)
            .map(|(elem, _)| elem)
            .collect();
        self.counted.output(kept).map_err(filter_floor_refusal)
    }
}

fn filter_floor_refusal(err: TemporalFloorRefusal) -> Outcome {
    Outcome::Incomplete(Effect::CoverageGap {
        reason: err.to_string(),
    })
}
