// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `TakeWhileSugar`: the `.take_while(pred)` adaptor. A decorator `Sugar` over an
// inner sequence-`Sugar` that keeps the leading run of elements where the closure
// const-evaluates true. Bails (None) on an opaque element in the kept prefix or a
// non-bool / runtime closure result. Lifted verbatim from the
// `Adaptor::TakeWhile(closure)` arm of the former `apply_one_adaptor` match.

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
        "take_while",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_take_while_good() {
                    let got = [1i32, 2, 3, 1].into_iter().take_while(|x| *x < 3).count();
                    assert_eq!(got, 2);
                }
            "#,
            r#"
                #[test]
                fn t_take_while_bad() {
                    let got = [1i32, 2, 3, 1].into_iter().take_while(|x| *x < 3).count();
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
    if call.method != "take_while" || call.args.len() != 1 {
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
    Some(Box::new(TakeWhileRecognizedSugar {
        inner: SugarBody::composite(&call.receiver, fcx),
        pred: BoolPredicateClosure::build(pred.clone(), fcx)?,
    }))
}

struct TakeWhileRecognizedSugar {
    inner: SugarBody<CompositeFloor>,
    pred: BoolPredicateClosure,
}

impl Sugar for TakeWhileRecognizedSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_take_while(&self.inner, &self.pred, ctx)
    }
}

/// Keep the leading run of elements where `pred` const-evaluates true.
pub(crate) struct TakeWhileSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) pred: BoolPredicateClosure,
}

impl Sugar for TakeWhileSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_take_while(&self.inner, &self.pred, ctx)
    }
}

fn reduce_take_while(
    inner: &SugarBody<CompositeFloor>,
    pred: &BoolPredicateClosure,
    ctx: &SugarCtx,
) -> Outcome {
    let seq = match inner.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_seq()
            .unwrap_or_else(|| take_while_gap("take_while receiver reduced to non-sequence")),
        Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
    };
    let floor = TakeWhileFloor::default();
    let operand = match floor.derived_operand(seq.len()) {
        Ok(operand) => operand,
        Err(outcome) => return outcome,
    };
    let output = match floor.desugar(operand, seq, |idx, elem| {
        pred.eval_for_elem(elem, idx, "take_while", ctx)
    }) {
        Ok(output) => output,
        Err(outcome) => return outcome,
    };
    ctx.record_adapter_floor_audit("take_while", output.standing().count());
    Outcome::Complete(Desugared::Seq(output.into_items()))
}

fn take_while_gap(reason: &str) -> ! {
    panic!("take_while did not reach a lawful floor: {reason}")
}

#[derive(Clone, Copy)]
struct TakeWhileFloor {
    counted: CountedAdapterFloor,
}

impl Default for TakeWhileFloor {
    fn default() -> Self {
        Self {
            counted: CountedAdapterFloor::new("take_while", AdapterOutputIterMember::take_while),
        }
    }
}

impl TakeWhileFloor {
    fn derived_operand(&self, count: usize) -> Result<IterStanding, Outcome> {
        self.counted
            .derived_operand(count)
            .map_err(take_while_floor_refusal)
    }

    fn desugar<F>(
        &self,
        _operand: IterStanding,
        seq: Vec<DesugaredElem>,
        mut predicate: F,
    ) -> Result<AdapterFloorOutput<DesugaredElem>, Outcome>
    where
        F: FnMut(usize, &DesugaredElem) -> Result<bool, Outcome>,
    {
        let mut refusal = None;
        let out = seq
            .into_iter()
            .enumerate()
            .take_while(|(idx, elem)| match predicate(*idx, elem) {
                Ok(keep) => keep,
                Err(outcome) => {
                    refusal = Some(outcome);
                    false
                }
            })
            .map(|(_, elem)| elem)
            .collect::<Vec<_>>();
        if let Some(outcome) = refusal {
            return Err(outcome);
        }
        self.counted.output(out).map_err(take_while_floor_refusal)
    }
}

fn take_while_floor_refusal(err: TemporalFloorRefusal) -> Outcome {
    Outcome::Incomplete(Effect::CoverageGap {
        reason: err.to_string(),
    })
}
