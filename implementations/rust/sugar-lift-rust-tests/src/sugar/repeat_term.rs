// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Repeat` (`[elem; N]`) in TERM position: a literal or
// scope-resolved const count expands to the N-fold `literal_aggregate_term` "Array";
// a runtime/opaque count is the `ArrayRepeatSugar` refuse-shape (`Effect::ArrayRepeat`).
// This is the TERM-position
// node — DISTINCT from the COMPOSITE-catalog `Expr::Repeat` (which boxes
// `decompose_array_repeat` directly as the refuse-shape). Byte-identical to the
// `Expr::Repeat` arm of the old fat factory.

use crate::sugar::aggregate_term::LiteralAggregateTermSugar;
use crate::sugar::array_repeat;
use crate::sugar::factory::{SugarBody, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("repeat_term", recognize);

/// TERM recognizer for `Expr::Repeat`.
/// No `as_expr()`, `Expr::`, or raw syn in this function.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let elem_frag = frag.repeat_elem_frag()?;
    let Some(count) = frag.repeat_len_in_scope(fcx) else {
        return Some(array_repeat::refusal_node(&frag.token_str()));
    };
    const MAX_REPEAT: usize = 4096;
    if count > MAX_REPEAT {
        return Some(array_repeat::refusal_node(&frag.token_str()));
    }
    Some(Box::new(LiteralAggregateTermSugar::new(
        "Array",
        std::iter::repeat_with(|| SugarBody::term_frag(&elem_frag, fcx))
            .take(count)
            .collect(),
    )))
}

// ---------------------------------------------------------------------------
// Phase-3 from_src tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::source_fragment::{parse_file, SourceFragment};
    use crate::{
        sugar_ctx, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, TemporalPlan, TemporalScope,
    };
    use std::collections::BTreeMap;
    use syn::{Expr, Item};

    /// from_src: `[42u8; 3]` -> SourceFragment -> observed "Other:Expr:Repeat" ->
    /// repeat_elem_frag + repeat_len_in_scope -> recognize -> Complete.
    /// No parse_quote!, no StubTerm, no run() helper.
    #[test]
    fn from_src_repeat_literal_count_floor() {
        let file = parse_file("fn f() { let _ = [42u8; 3]; }");
        let Item::Fn(ref f) = file.items[0] else {
            panic!("expected fn")
        };
        let syn::Stmt::Local(ref loc) = f.block.stmts[0] else {
            panic!("expected local")
        };
        let repeat_expr = &*loc.init.as_ref().expect("no init").expr;
        let frag = SourceFragment::expr(repeat_expr, "<test>");

        // Gate: observed shape must be "Other:Expr:Repeat".
        assert_eq!(
            frag.observed(),
            "Other:Expr:Repeat",
            "fragment must observe as Repeat"
        );

        // Accessor gate: repeat_elem_frag returns the element.
        let elem_frag = frag
            .repeat_elem_frag()
            .expect("repeat_elem_frag must return Some");
        assert_eq!(
            elem_frag.observed(),
            "PrimitiveLiteral",
            "element must be a PrimitiveLiteral"
        );

        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        // Accessor gate: repeat_len_in_scope resolves literal 3.
        let count = frag
            .repeat_len_in_scope(&fcx)
            .expect("repeat_len_in_scope must return Some for literal count");
        assert_eq!(count, 3, "count must be 3");

        // Build via recognize (the actual entry point).
        let sugar_box = recognize(&frag, &fcx).expect("recognize must return Some for [42u8; 3]");

        // Desugar with a minimal real ctx (no run() helper).
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut fw = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut fw, 0);
        let outcome = sugar_box.reduce(&ctx);
        assert!(
            matches!(outcome, Outcome::Complete(_)),
            "desugar must complete for literal-count repeat"
        );
    }

    /// Discrimination: `[0u8; N]` with `N` not in scope -> recognize returns
    /// Some(refusal) -> Incomplete (not None).
    #[test]
    fn from_src_repeat_runtime_count_refusal() {
        let file = parse_file("fn f() { let _ = [0u8; N]; }");
        let Item::Fn(ref f) = file.items[0] else {
            panic!("expected fn")
        };
        let syn::Stmt::Local(ref loc) = f.block.stmts[0] else {
            panic!("expected local")
        };
        let repeat_expr = &*loc.init.as_ref().expect("no init").expr;
        let frag = SourceFragment::expr(repeat_expr, "<test>");

        assert_eq!(frag.observed(), "Other:Expr:Repeat");

        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        // N is not in scope: repeat_len_in_scope returns None.
        assert!(
            frag.repeat_len_in_scope(&fcx).is_none(),
            "N not in scope must yield None"
        );

        // recognize returns Some (a refusal node), not None.
        let sugar_box =
            recognize(&frag, &fcx).expect("recognize must return Some(refusal) for [0u8; N]");

        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut fw = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut fw, 0);
        assert!(
            matches!(sugar_box.reduce(&ctx), Outcome::Incomplete(_)),
            "refusal node must produce Incomplete"
        );
    }

    /// Structural: a non-Repeat expression yields None from recognize.
    #[test]
    fn from_src_non_repeat_not_recognized() {
        let expr: Expr = syn::parse_str("x + 1").expect("parse");
        let frag = SourceFragment::expr(&expr, "<test>");

        assert_ne!(frag.observed(), "Other:Expr:Repeat");
        assert!(
            frag.repeat_elem_frag().is_none(),
            "non-Repeat must have no repeat_elem_frag"
        );

        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "non-Repeat must not be recognized"
        );
    }
}
