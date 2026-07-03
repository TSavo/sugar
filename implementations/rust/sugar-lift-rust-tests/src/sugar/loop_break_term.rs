// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for the value-transparent `loop { break expr; }` shape.

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "loop_break_term",
        crate::sugar::claim::SugarWitnesses::Pending,
        recognize,
    );

/// No `as_expr()`, `Expr::`, or raw syn in this function.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let payload = frag.loop_single_break_payload_frag()?;
    Some(Box::new(LoopBreakTermSugar {
        payload: SugarBody::term_frag(&payload, fcx),
    }))
}

struct LoopBreakTermSugar {
    payload: SugarBody<TermFloor>,
}

impl Sugar for LoopBreakTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.payload.desugar(ctx)
    }
}

// ---------------------------------------------------------------------------
// Phase-3 from_src tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use crate::{LiftOptions, TemporalPlan, TemporalScope};
    use std::collections::BTreeMap;
    use syn::Expr;

    /// Positive: `loop { break 42_i32; }` is a Loop with a single unlabeled break;
    /// `loop_single_break_payload_frag()` returns the payload expression.
    #[test]
    fn from_src_loop_single_break_has_payload() {
        let expr: Expr = syn::parse_str("loop { break 42_i32; }").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert!(
            frag.observed().contains("Loop"),
            "observed={}",
            frag.observed()
        );
        let payload = frag.loop_single_break_payload_frag();
        assert!(
            payload.is_some(),
            "single break must have a payload fragment"
        );
        assert_eq!(payload.unwrap().observed(), "PrimitiveLiteral");

        let scope = TemporalScope::new("loop-break-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_some(),
            "loop{{break}} must be recognized"
        );
    }

    /// Discrimination: `loop { x += 1; }` has no break, returns None.
    #[test]
    fn from_src_loop_no_break_not_recognized() {
        let expr: Expr = syn::parse_str("loop { let x = 1; }").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert!(
            frag.loop_single_break_payload_frag().is_none(),
            "no break -> no payload"
        );

        let scope = TemporalScope::new("loop-break-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "loop without single break must not be recognized"
        );
    }

    /// Structural: a BinOp is not a Loop.
    #[test]
    fn from_src_binop_not_loop() {
        let expr: Expr = syn::parse_str("x + 1").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert!(frag.loop_single_break_payload_frag().is_none());

        let scope = TemporalScope::new("loop-break-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(recognize(&frag, &fcx).is_none());
    }
}
