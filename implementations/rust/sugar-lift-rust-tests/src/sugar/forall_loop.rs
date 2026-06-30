// SPDX-License-Identifier: Apache-2.0
//
// `for <var> in <literal-domain>` bounded universal sugar.

use std::collections::BTreeMap;

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::forall;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::statement_position;
use crate::{
    FactoryAuditLog, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar, TemporalScope,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("forall_loop", recognize);

/// No `as_expr()`, `Expr::`, or raw syn in this function.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    forall::decompose_for_loop_frag(frag, fcx.scope(), fcx.let_inits(), fcx)
        .map(|node| Box::new(node) as Box<dyn Sugar>)
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn desugar_statement_for_loop(
    expr: &Expr,
    scope: &TemporalScope,
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    float_widths: &mut FloatWidthScope,
    let_inits: &BTreeMap<String, &Expr>,
    macro_depth: usize,
    factory_audits: Option<&FactoryAuditLog>,
) -> Outcome {
    statement_position::desugar_composite_expr(
        expr,
        scope,
        options,
        reducer,
        float_widths,
        let_inits,
        macro_depth,
        factory_audits,
    )
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

    /// Positive: `decompose_for_loop_frag` gate check -- a ForLoop expression
    /// enters the wrapper. Verifies observed() returns the ForLoop discriminant.
    #[test]
    fn from_src_for_loop_observed_is_forloop() {
        let expr: Expr = syn::parse_str("for x in [1_i32, 2, 3] { let _ = x; }").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");
        // ForLoop maps to "Other:Expr:ForLoop" via the discriminant catch-all
        assert!(
            frag.observed().contains("ForLoop"),
            "observed={}",
            frag.observed()
        );
    }

    /// Discrimination: a method call is not a ForLoop.
    #[test]
    fn from_src_method_call_not_for_loop() {
        let expr: Expr =
            syn::parse_str("[1_i32].iter().for_each(|x| { let _ = x; })").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert!(frag.call_is_method_call(), "must be MethodCall");
        assert!(!frag.observed().contains("ForLoop"), "must not be ForLoop");

        let scope = TemporalScope::new("forall-loop-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "method call must not be recognized as forall_loop"
        );
    }

    /// Structural: a BinOp is neither a ForLoop nor a MethodCall.
    #[test]
    fn from_src_binop_not_for_loop() {
        let expr: Expr = syn::parse_str("x + 1").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert!(!frag.observed().contains("ForLoop"));

        let scope = TemporalScope::new("forall-loop-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "BinOp must not be recognized"
        );
    }
}
