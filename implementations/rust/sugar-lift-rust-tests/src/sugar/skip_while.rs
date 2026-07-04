// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `SkipWhileSugar`: the `.skip_while(pred)` adaptor. A decorator `Sugar` over an
// inner sequence-`Sugar` that drops the leading run of elements where the closure
// const-evaluates true. Bails (None) on an opaque element in the skipped prefix or
// a non-bool / runtime closure result. Lifted verbatim from the
// `Adaptor::SkipWhile(closure)` arm of the former `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::bool_predicate::{BoolPredicateClosure, BoolPredicateFunction};
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
        "skip_while",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_skip_while_good() {
                    let got = [1i32, 2, 3, 1].into_iter().skip_while(|x| *x < 3).count();
                    assert_eq!(got, 2);
                }
            "#,
            r#"
                #[test]
                fn t_skip_while_bad() {
                    let got = [1i32, 2, 3, 1].into_iter().skip_while(|x| *x < 3).count();
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
    if call.method != "skip_while" || call.args.len() != 1 {
        return None;
    }
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits())
        && !has_composite(&call.receiver, fcx)
    {
        return None;
    }
    Some(Box::new(SkipWhileRecognizedSugar {
        inner: SugarBody::composite(&call.receiver, fcx),
        pred: SkipWhilePredicate::build(&call.args[0], fcx)?,
    }))
}

pub(crate) enum SkipWhilePredicate {
    Closure(BoolPredicateClosure),
    Function(BoolPredicateFunction),
}

impl SkipWhilePredicate {
    pub(crate) fn build(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Self> {
        Self::build_result(expr, fcx).ok()
    }

    pub(crate) fn build_result(expr: &Expr, fcx: &SugarBuildCtx) -> Result<Self, String> {
        match crate::strip_refs_groups(expr) {
            Expr::Closure(pred) => BoolPredicateClosure::build(pred.clone(), fcx)
                .map(Self::Closure)
                .ok_or_else(|| {
                    format!(
                        "skip_while closure predicate `{}` is not unary",
                        crate::token_key(expr)
                    )
                }),
            other => BoolPredicateFunction::build_result(other.clone(), fcx).map(Self::Function),
        }
    }

    fn eval_for_elem(
        &self,
        elem: &crate::DesugaredElem,
        ordinal: usize,
        family: &'static str,
        ctx: &SugarCtx,
    ) -> Result<bool, Outcome> {
        match self {
            Self::Closure(pred) => pred.eval_for_elem(elem, ordinal, family, ctx),
            Self::Function(pred) => pred.eval_for_elem(elem, ordinal, family, ctx),
        }
    }
}

struct SkipWhileRecognizedSugar {
    inner: SugarBody<CompositeFloor>,
    pred: SkipWhilePredicate,
}

impl Sugar for SkipWhileRecognizedSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_skip_while(&self.inner, &self.pred, ctx)
    }
}

/// Drop the leading run of elements where `pred` const-evaluates true.
pub(crate) struct SkipWhileSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) pred: SkipWhilePredicate,
}

impl Sugar for SkipWhileSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_skip_while(&self.inner, &self.pred, ctx)
    }
}

fn reduce_skip_while(
    inner: &SugarBody<CompositeFloor>,
    pred: &SkipWhilePredicate,
    ctx: &SugarCtx,
) -> Outcome {
    let seq = match inner.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_seq()
            .unwrap_or_else(|| skip_while_gap("skip_while receiver reduced to non-sequence")),
        Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
    };
    let floor = SkipWhileFloor::default();
    let operand = match floor.derived_operand(seq.len()) {
        Ok(operand) => operand,
        Err(outcome) => return outcome,
    };
    let output = match floor.desugar(operand, seq, |idx, elem| {
        pred.eval_for_elem(elem, idx, "skip_while", ctx)
    }) {
        Ok(output) => output,
        Err(outcome) => return outcome,
    };
    ctx.record_adapter_floor_audit("skip_while", output.standing().count());
    Outcome::Complete(Desugared::Seq(output.into_items()))
}

fn skip_while_gap(reason: &str) -> ! {
    panic!("skip_while did not reach a lawful floor: {reason}")
}

#[derive(Clone, Copy)]
struct SkipWhileFloor {
    counted: CountedAdapterFloor,
}

impl Default for SkipWhileFloor {
    fn default() -> Self {
        Self {
            counted: CountedAdapterFloor::new("skip_while", AdapterOutputIterMember::skip_while),
        }
    }
}

impl SkipWhileFloor {
    fn derived_operand(&self, count: usize) -> Result<IterStanding, Outcome> {
        self.counted
            .derived_operand(count)
            .map_err(skip_while_floor_refusal)
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
            .skip_while(|(idx, elem)| match predicate(*idx, elem) {
                Ok(skip) => skip,
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
        self.counted.output(out).map_err(skip_while_floor_refusal)
    }
}

fn skip_while_floor_refusal(err: TemporalFloorRefusal) -> Outcome {
    Outcome::Incomplete(Effect::CoverageGap {
        reason: err.to_string(),
    })
}
