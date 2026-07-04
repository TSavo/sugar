// SPDX-License-Identifier: Apache-2.0
//
// `SkipSugar`: the `.skip(n)` adaptor. A decorator `Sugar` over an inner
// sequence-`Sugar` that drops the first `n` elements. Lifted verbatim from the
// `Adaptor::Skip(n)` arm of the former `apply_one_adaptor` match.

use syn::Expr;

use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::temporal_floor::{
    AdapterFloorOutput, AdapterOutputIterMember, CountedAdapterFloor, IterStanding,
    TemporalFloorRefusal,
};
use crate::{const_int, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "skip",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_skip_good() {
                    let got = [1i32, 2, 3].into_iter().skip(2).count();
                    assert_eq!(got, 1);
                }
            "#,
            r#"
                #[test]
                fn t_skip_bad() {
                    let got = [1i32, 2, 3].into_iter().skip(2).count();
                    assert_eq!(got, 2);
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
    if call.method != "skip" || call.args.len() != 1 {
        return None;
    }
    if !has_composite(&call.receiver, fcx) {
        return None;
    }
    let n: usize = const_int(&call.args[0])?.try_into().ok()?;
    Some(Box::new(SkipSugar {
        inner: SugarBody::composite(&call.receiver, fcx),
        n,
    }))
}

/// Drop the first `n` elements of the inner sequence.
pub(crate) struct SkipSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) n: usize,
}

impl Sugar for SkipSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.inner.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_seq()
                .unwrap_or_else(|| skip_gap("skip receiver reduced to non-sequence")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let floor = SkipFloor::default();
        let operand = match floor.derived_operand(seq.len()) {
            Ok(operand) => operand,
            Err(outcome) => return outcome,
        };
        let output = match floor.desugar(operand, seq, self.n) {
            Ok(output) => output,
            Err(outcome) => return outcome,
        };
        ctx.record_adapter_floor_audit("skip", output.standing().count());
        Outcome::Complete(Desugared::Seq(output.into_items()))
    }
}

fn skip_gap(reason: &str) -> ! {
    panic!("skip did not reach a lawful floor: {reason}")
}

#[derive(Clone, Copy)]
struct SkipFloor {
    counted: CountedAdapterFloor,
}

impl Default for SkipFloor {
    fn default() -> Self {
        Self {
            counted: CountedAdapterFloor::new("skip", AdapterOutputIterMember::skip),
        }
    }
}

impl SkipFloor {
    fn derived_operand(&self, count: usize) -> Result<IterStanding, Outcome> {
        self.counted
            .derived_operand(count)
            .map_err(skip_floor_refusal)
    }

    fn desugar(
        &self,
        operand: IterStanding,
        seq: Vec<DesugaredElem>,
        n: usize,
    ) -> Result<AdapterFloorOutput<DesugaredElem>, Outcome> {
        let expected = operand.count().saturating_sub(n);
        let out = seq.into_iter().skip(n).collect::<Vec<_>>();
        self.counted
            .assert_output_count(&operand, expected, out.len())
            .map_err(skip_floor_refusal)?;
        self.counted.output(out).map_err(skip_floor_refusal)
    }
}

fn skip_floor_refusal(err: TemporalFloorRefusal) -> Outcome {
    Outcome::Incomplete(Effect::CoverageGap {
        reason: err.to_string(),
    })
}
