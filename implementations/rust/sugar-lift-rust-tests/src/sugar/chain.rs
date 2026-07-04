// SPDX-License-Identifier: Apache-2.0
//
// `ChainSugar`: `.chain(rhs)` over two finite literal-derived sequences. This is a
// domain transform, not a terminal method call: the left and right receivers are
// both built through the composite factory, then concatenated in source order.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::literal::EMPTY_DOMAIN_REASON;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::temporal_floor::{
    AdapterFloorOutput, AdapterOutputIterMember, CountedAdapterFloor, IterStanding,
    TemporalFloorRefusal,
};
use crate::{
    const_val_term, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "chain",
    SugarRole::Composite,
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            #[test]
            fn t_chain_good() {
                let got = [1i32, 2].into_iter().chain([3, 4]).count();
                assert_eq!(got, 4);
            }
        "#,
        r#"
            #[test]
            fn t_chain_bad() {
                let got = [1i32, 2].into_iter().chain([3, 4]).count();
                assert_eq!(got, 5);
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
    if call.method != "chain" || call.args.len() != 1 {
        return None;
    }
    // Both operands resolve through the FACTORY (`has_composite`/`build_composite`). A
    // bare `&ys` RHS is now a first-class composite (`reference_sequence` recognizer), so
    // no per-adaptor literal-sequence fallback is needed here.
    if !has_composite(&call.receiver, fcx) || !has_composite(&call.args[0], fcx) {
        return None;
    }
    Some(ChainSugar::new(
        SugarBody::composite(&call.receiver, fcx),
        SugarBody::composite(&call.args[0], fcx),
    ))
}

struct ChainSugar {
    left: SugarBody<CompositeFloor>,
    right: SugarBody<CompositeFloor>,
}

impl ChainSugar {
    fn new(left: SugarBody<CompositeFloor>, right: SugarBody<CompositeFloor>) -> Box<dyn Sugar> {
        Box::new(Self { left, right })
    }
}

impl Sugar for ChainSugar {
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        let left = match sequence_from_body(&self.left, ctx, "chain lhs") {
            Ok(seq) => seq,
            Err(outcome) => return outcome,
        };
        let right = match sequence_from_body(&self.right, ctx, "chain rhs") {
            Ok(seq) => seq,
            Err(outcome) => return outcome,
        };
        let total = left
            .len()
            .checked_add(right.len())
            .unwrap_or_else(|| panic!("chain sequence length overflow"));
        if total > SUGAR_SEQ_CAP as usize {
            panic!("chain sequence length {total} exceeds cap {SUGAR_SEQ_CAP}");
        }
        let floor = ChainFloor::default();
        let left_operand = match floor.derived_operand(left.len()) {
            Ok(operand) => operand,
            Err(outcome) => return outcome,
        };
        let right_operand = match floor.derived_operand(right.len()) {
            Ok(operand) => operand,
            Err(outcome) => return outcome,
        };
        let desugared = match (left, right) {
            (ChainSequence::Values(left), ChainSequence::Values(right)) => {
                let output = match floor.desugar(left_operand, right_operand, left, right) {
                    Ok(output) => output,
                    Err(outcome) => return outcome,
                };
                ctx.record_adapter_floor_audit("chain", output.standing().count());
                Desugared::Seq(output.into_items())
            }
            (left, right) => {
                let output = match floor.desugar(
                    left_operand,
                    right_operand,
                    left.into_terms("chain lhs"),
                    right.into_terms("chain rhs"),
                ) {
                    Ok(output) => output,
                    Err(outcome) => return outcome,
                };
                ctx.record_adapter_floor_audit("chain", output.standing().count());
                Desugared::TermSeq(output.into_items())
            }
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::chain",
            len = total,
            "chained finite literal-derived domain"
        );
        Outcome::Complete(desugared)
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

#[derive(Clone, Copy)]
struct ChainFloor {
    counted: CountedAdapterFloor,
}

impl Default for ChainFloor {
    fn default() -> Self {
        Self {
            counted: CountedAdapterFloor::new("chain", AdapterOutputIterMember::chain),
        }
    }
}

impl ChainFloor {
    fn derived_operand(&self, count: usize) -> Result<IterStanding, Outcome> {
        self.counted
            .derived_operand(count)
            .map_err(chain_floor_refusal)
    }

    fn desugar<T>(
        &self,
        left_operand: IterStanding,
        right_operand: IterStanding,
        left: Vec<T>,
        right: Vec<T>,
    ) -> Result<AdapterFloorOutput<T>, Outcome> {
        let expected = left_operand
            .count()
            .checked_add(right_operand.count())
            .unwrap_or_else(|| panic!("chain operand count overflow"));
        let out = left.into_iter().chain(right).collect::<Vec<_>>();
        self.counted
            .assert_output_count(&left_operand, expected, out.len())
            .map_err(chain_floor_refusal)?;
        self.counted.output(out).map_err(chain_floor_refusal)
    }
}

fn chain_floor_refusal(err: TemporalFloorRefusal) -> Outcome {
    Outcome::Incomplete(Effect::CoverageGap {
        reason: err.to_string(),
    })
}

fn sequence_from_body(
    body: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
    label: &'static str,
) -> Result<ChainSequence, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(Desugared::Seq(seq)) => Ok(ChainSequence::Values(seq)),
        Outcome::Complete(Desugared::TermSeq(terms)) => Ok(ChainSequence::Terms(terms)),
        Outcome::Complete(_) => panic!("{label} reduced to non-sequence"),
        Outcome::Incomplete(effect) if effect.is_literal_domain_reason(EMPTY_DOMAIN_REASON) => {
            Ok(ChainSequence::Values(Vec::new()))
        }
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

enum ChainSequence {
    Values(Vec<DesugaredElem>),
    Terms(Vec<Rc<Term>>),
}

impl ChainSequence {
    fn len(&self) -> usize {
        match self {
            ChainSequence::Values(seq) => seq.len(),
            ChainSequence::Terms(terms) => terms.len(),
        }
    }

    fn into_terms(self, owner: &str) -> Vec<Rc<Term>> {
        match self {
            ChainSequence::Values(seq) => seq
                .iter()
                .map(|elem| {
                    elem.value
                        .as_ref()
                        .and_then(const_val_term)
                        .unwrap_or_else(|| {
                            panic!(
                                "{owner} sequence element did not dispatch to a literal term floor"
                            )
                        })
                })
                .collect(),
            ChainSequence::Terms(terms) => terms,
        }
    }
}
