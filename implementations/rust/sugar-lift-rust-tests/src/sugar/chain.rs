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
use crate::{const_val_term, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "chain",
    SugarRole::Composite,
    crate::sugar::claim::SugarWitnesses::Pending,
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
        let floor = match (left, right) {
            (ChainSequence::Values(mut left), ChainSequence::Values(right)) => {
                left.extend(right);
                Desugared::Seq(left)
            }
            (left, right) => {
                let mut terms = left.into_terms("chain lhs");
                terms.extend(right.into_terms("chain rhs"));
                Desugared::TermSeq(terms)
            }
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::chain",
            len = total,
            "chained finite literal-derived domain"
        );
        Outcome::Complete(floor)
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
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
