// SPDX-License-Identifier: Apache-2.0
//
// `.for_each(|var| body)` bounded universal sugar.

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::forall;
use crate::sugar::source_fragment::SourceFragment;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("for_each", recognize);

/// No `as_expr()`, `Expr::`, or raw syn in this function.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if !frag.call_is_method_call() {
        return None;
    }
    forall::decompose_for_each_frag(frag, fcx.let_inits(), fcx)
        .map(|node| Box::new(node) as Box<dyn Sugar>)
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

    /// Positive: `[1_i32, 2, 3].iter().for_each(|x| { let _ = x; })` is a MethodCall.
    /// Verifies that call_is_method_call() gates correctly.
    #[test]
    fn from_src_for_each_is_method_call() {
        let expr: Expr =
            syn::parse_str("[1_i32].iter().for_each(|x| { let _ = x; })").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");
        assert!(frag.call_is_method_call(), "for_each must be a MethodCall");
        assert_eq!(frag.call_method_key().as_deref(), Some("for_each"));
    }

    /// Discrimination: a binop is not a method call and returns None from recognize.
    #[test]
    fn from_src_binop_not_for_each() {
        let expr: Expr = syn::parse_str("x + 1").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert!(
            !frag.call_is_method_call(),
            "binop must not be a MethodCall"
        );

        let scope = TemporalScope::new("for-each-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "BinOp must not be recognized"
        );
    }

    /// Structural: a method call with the wrong name (.map) is not recognized.
    #[test]
    fn from_src_map_method_not_for_each() {
        let expr: Expr = syn::parse_str("[1_i32].iter().map(|x| x)").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert!(frag.call_is_method_call(), "map must be a MethodCall");
        assert_eq!(frag.call_method_key().as_deref(), Some("map"));

        let scope = TemporalScope::new("for-each-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        // .map is not .for_each, so recognize returns None
        assert!(
            recognize(&frag, &fcx).is_none(),
            ".map must not be recognized as for_each"
        );
    }
}
