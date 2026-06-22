// SPDX-License-Identifier: Apache-2.0
//
// `ChainSugar`: `.chain(rhs)` over two finite literal-derived sequences. This is a
// domain transform, not a terminal method call: the left and right receivers are
// both built through the composite factory, then concatenated in source order.

use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_composite, has_composite, SugarBuildCtx};
use crate::{Desugared, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP};

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
    Some(Box::new(ChainSugar {
        left: build_composite(&call.receiver, fcx),
        right: build_composite(&call.args[0], fcx),
    }))
}

struct ChainSugar {
    left: Box<dyn Sugar>,
    right: Box<dyn Sugar>,
}

impl Sugar for ChainSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let mut left = self.left.desugar(ctx).dug()?.into_seq()?;
            let right = self.right.desugar(ctx).dug()?.into_seq()?;
            let total = left.len().checked_add(right.len())?;
            if total as i64 > SUGAR_SEQ_CAP {
                return None;
            }
            left.extend(right);
            debug!(
                target: "sugar_lift_rust_tests::sugar::chain",
                len = left.len(),
                "chained finite literal-derived domain"
            );
            Some(Desugared::Seq(left))
        })())
    }
}
