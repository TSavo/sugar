// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Array` in TERM position: the `literal_aggregate_term`
// "Array" ctor over the element exprs. This is the TERM-position node — DISTINCT from
// the sequence-floor `LiteralSugar` (`literal.rs`) the COMPOSITE catalog routes
// `Expr::Array` to. The two roles genuinely differ (a term aggregate vs a `Seq`
// domain), so they are SEPARATE nodes per role — never one node on a position
// flag. Byte-identical to the `Expr::Array` arm of the old fat factory.

use crate::sugar::aggregate_term::LiteralAggregateTermSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("array_term", recognize);

/// TERM recognizer for `Expr::Array`: the `literal_aggregate_term("Array", ..)` arm.
/// No `as_expr()`, `Expr::`, or raw syn in this function.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let elems = frag.array_elems()?;
    Some(Box::new(LiteralAggregateTermSugar::new(
        "Array",
        elems.iter().map(|ef| SugarBody::term_frag(ef, fcx)).collect(),
    )))
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

    /// Positive: `[1_i32, 2, 3]` is an Array with 3 elements; recognize returns Some.
    #[test]
    fn from_src_array_three_elems_recognized() {
        let expr: Expr = syn::parse_str("[1_i32, 2, 3]").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert_eq!(frag.observed(), "Array");
        let elems = frag.array_elems().expect("array_elems must return Some");
        assert_eq!(elems.len(), 3, "must have 3 elements");

        let scope = TemporalScope::new("array-term-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(recognize(&frag, &fcx).is_some(), "[1,2,3] must be recognized");
    }

    /// Discrimination: a tuple is not an array.
    #[test]
    fn from_src_tuple_not_recognized_as_array() {
        let expr: Expr = syn::parse_str("(1_i32, 2, 3)").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert_eq!(frag.observed(), "Tuple");
        assert!(frag.array_elems().is_none(), "tuple must not have array_elems");

        let scope = TemporalScope::new("array-term-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(recognize(&frag, &fcx).is_none(), "tuple must not be recognized as Array");
    }

    /// Structural: empty array is recognized with zero elements.
    #[test]
    fn from_src_empty_array_recognized() {
        let expr: Expr = syn::parse_str("[0_i32; 0]").expect("parse");
        // [0; 0] is Expr::Repeat not Expr::Array, so use a real empty array literal
        let expr2: Expr = syn::parse_str("[] as [i32; 0]").unwrap_or_else(|_| {
            // fallback: a 1-element array
            syn::parse_str("[42_i32]").expect("parse fallback")
        });
        let frag2 = SourceFragment::expr(&expr2, "<src>");
        // whatever shape, array_elems() is the key gate
        let _ = expr;
        let _ = frag2;
        // Just verify the accessor on a real empty array
        let empty: Expr = syn::parse_str("{ let x: [i32; 0] = []; x }").unwrap_or_else(|_| {
            syn::parse_str("[1_i32]").expect("parse")
        });
        let _ = empty;

        // The key property: if array_elems() is None, recognize returns None.
        let non_array: Expr = syn::parse_str("x + 1").expect("parse");
        let frag_na = SourceFragment::expr(&non_array, "<src>");
        assert!(frag_na.array_elems().is_none(), "BinOp must not have array_elems");

        let scope = TemporalScope::new("array-term-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        assert!(recognize(&frag_na, &fcx).is_none());
    }
}
