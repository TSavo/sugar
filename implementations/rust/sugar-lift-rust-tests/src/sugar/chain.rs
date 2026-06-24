// SPDX-License-Identifier: Apache-2.0
//
// `ChainSugar`: `.chain(rhs)` over two finite literal-derived sequences. This is a
// domain transform, not a terminal method call: the left and right receivers are
// both built through the composite factory, then concatenated in source order.

use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::{Desugared, DesugaredElem, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("chain", SugarRole::Composite, recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
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
        let mut left = match sequence_from_body(&self.left, ctx, "chain lhs") {
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
        left.extend(right);
        debug!(
            target: "sugar_lift_rust_tests::sugar::chain",
            len = left.len(),
            "chained finite literal-derived domain"
        );
        Outcome::Complete(Desugared::Seq(left))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

fn sequence_from_body(
    body: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
    label: &'static str,
) -> Result<Vec<DesugaredElem>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_seq()
            .unwrap_or_else(|| panic!("{label} reduced to non-sequence"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}
