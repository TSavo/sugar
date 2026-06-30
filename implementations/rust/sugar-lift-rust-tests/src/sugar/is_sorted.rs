// SPDX-License-Identifier: Apache-2.0
//
// `IsSortedSugar`: `.is_sorted()` over a literal array -- directly, or behind an
// order-PRESERVING view/iter adaptor (`.iter()` / `.into_iter()` / `.iter_mut()`
// / `.copied()` / `.cloned()` / `.as_slice()` / `.by_ref()`) -- is value sugar.
// Sortedness is determined entirely by the literal elements, so we COMPUTE it at
// recognize time and lower a ground `Bool`, replacing the opaque
// `method:is_sorted` EUF var (which had no teeth).
//
// THE RULE. std `is_sorted` is the NON-STRICT consecutive-pair rule: sorted iff
// every adjacent pair `v[i] <= v[i+1]` (so `[1,2,2,9]` is sorted; `[1,3,2]` is
// not). The empty and single-element cases are trivially sorted (true).
//
// EXACT-OR-NONE. We claim ONLY when the receiver bottoms out to a literal array
// of CLOSED SCALAR elements (int/byte/char/bool, allowing a unary `-`), each of
// which folds to its exact ordering value (codepoint for `char`, 0/1 for `bool`).
// A runtime receiver, a non-literal element, the closure-bearing
// `is_sorted_by`/`is_sorted_by_key` (args present), or an order-CHANGING adaptor
// (e.g. `.rev()`) is NOT matched -> we decline, leaving the existing opaque
// handling (no regression, never a guess).
//
// TEETH. `[1,3,2].iter().is_sorted()` folds to `Bool(false)` -> asserting it is
// z3-UNSAT (REFUTED); `[1,2,2,9].iter().is_sorted()` -> `Bool(true)` ->
// discharged.
//
// DEEP MIGRATION (Phase-3 ratchet -- FULLY MIGRATED).
//   * `recognize` uses ONLY typed `SourceFragment` accessors:
//     `call_is_method_call`, `call_target_name`, `call_arg_count`,
//     `call_receiver`, `scalar_array_ordered_values`,
//     `is_order_preserving_view_adaptor`. No `as_expr()`, no raw `Expr::` match.
//   * `IsSortedSugar` holds `value: bool` only -- no raw syn field.

use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{bool_const, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("is_sorted", SugarRole::Term, recognize);

fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Must be a MethodCall named `is_sorted` with no args.
    // `is_sorted_by`/`is_sorted_by_key` carry a closure argument; decline those.
    if !frag.call_is_method_call() {
        return None;
    }
    if frag.call_target_name().as_deref() != Some("is_sorted") {
        return None;
    }
    if frag.call_arg_count() != 0 {
        return None;
    }
    // Walk the receiver, peeling order-PRESERVING view/iter adaptors, until we
    // reach a literal scalar array whose elements we can fold to i128.
    let mut recv = frag.call_receiver()?;
    loop {
        if let Some(vals) = recv.scalar_array_ordered_values() {
            // std `is_sorted`: non-strict consecutive pairs. Empty/single -> true.
            let sorted = vals.windows(2).all(|w| w[0] <= w[1]);
            return Some(Box::new(IsSortedSugar { value: sorted }));
        }
        // Peel one order-PRESERVING adaptor (iter/into_iter/copied/etc.) and retry.
        // An order-CHANGING adaptor (rev) or a runtime receiver -> decline.
        if recv.is_order_preserving_view_adaptor() {
            recv = recv.call_receiver()?;
        } else {
            return None;
        }
    }
}

struct IsSortedSugar {
    value: bool,
}

impl Sugar for IsSortedSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::sugar::is_sorted",
            value = self.value,
            "resolved literal-array is_sorted stdlib axiom to a ground bool"
        );
        Outcome::Complete(Desugared::Term(bool_const(self.value)))
    }
}

// ---------------------------------------------------------------------------
// from_src tests: source string -> SourceFragment -> observed -> build -> floor
// No parse_quote!, no StubTerm, no run(). Typed-accessor door only.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::factory::SugarBuildCtx;
    use crate::sugar::source_fragment::SourceFragment;
    use crate::{
        sugar_ctx, Desugared, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, TemporalPlan,
        TemporalScope,
    };
    use std::collections::BTreeMap;
    use sugar_ir_symbolic::{ConstValue, Term};
    use syn::Expr;

    /// Parse an expression string, wrap in a SourceFragment, call `recognize`,
    /// then `desugar`, and extract the ground `bool` from the resulting
    /// `Outcome::Complete(Desugared::Term(Bool(..)))`. Returns `None` when
    /// `recognize` declines (correct for all "must not fold" cases).
    fn desugar_bool(src: &str) -> Option<bool> {
        let expr: Expr = syn::parse_str(src).expect("parse expr");
        let scope = TemporalScope::new("is-sorted-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let frag = SourceFragment::expr(&expr, "<src>");
        let sugar = recognize(&frag, &fcx)?;
        let items = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        match sugar.desugar(&ctx) {
            Outcome::Complete(Desugared::Term(term)) => match term.as_ref() {
                Term::Const {
                    value: ConstValue::Bool(b),
                    ..
                } => Some(*b),
                _ => panic!("expected Bool const from is_sorted desugar"),
            },
            Outcome::Incomplete(_) => panic!("expected Outcome::Complete from is_sorted desugar"),
            _ => panic!("expected Outcome::Complete(Desugared::Term) from is_sorted desugar"),
        }
    }

    // --- failing from_src test (written first, before recognize was rewritten) ---

    /// `[1, 2, 2, 9].iter().is_sorted()` must fold to `true` via the typed
    /// accessor door (no raw Expr:: in recognize; observed is "MethodCall").
    #[test]
    fn from_src_sorted_array_iter_folds_true() {
        let expr: Expr = syn::parse_str("[1, 2, 2, 9].iter().is_sorted()").expect("parse expr");
        let frag = SourceFragment::expr(&expr, "<src>");

        // observed: the outermost node is a method call
        assert_eq!(frag.observed(), "MethodCall");

        // build: recognize must return Some (was failing before migration
        //        because as_expr() shim was the only path in)
        let scope = TemporalScope::new("is-sorted-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let sugar =
            recognize(&frag, &fcx).expect("recognize must succeed for sorted literal-array iter");

        // floor: desugar must produce Bool(true)
        let items = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        match sugar.desugar(&ctx) {
            Outcome::Complete(Desugared::Term(term)) => match term.as_ref() {
                Term::Const {
                    value: ConstValue::Bool(true),
                    ..
                } => {}
                _ => panic!("[1,2,2,9].iter().is_sorted() must fold to Bool(true)"),
            },
            Outcome::Incomplete(_) => panic!("must Complete, got Incomplete"),
            _ => panic!("must Outcome::Complete(Desugared::Term)"),
        }
    }

    // --- additional coverage ---

    #[test]
    fn from_src_unsorted_array_iter_folds_false() {
        // [1, 3, 2].iter().is_sorted() -> Bool(false)
        assert_eq!(desugar_bool("[1, 3, 2].iter().is_sorted()"), Some(false));
    }

    #[test]
    fn from_src_direct_array_no_adaptor_descending_false() {
        // [3, 2, 1].is_sorted() -> Bool(false)  (no .iter() needed)
        assert_eq!(desugar_bool("[3, 2, 1].is_sorted()"), Some(false));
    }

    #[test]
    fn from_src_order_changing_adaptor_declines() {
        // .rev() is order-CHANGING -> recognize returns None
        assert!(
            desugar_bool("[1, 2, 3].iter().rev().is_sorted()").is_none(),
            ".rev() is order-changing; is_sorted must decline"
        );
    }

    #[test]
    fn from_src_is_sorted_by_with_closure_declines() {
        // is_sorted_by carries an arg -> decline
        assert!(
            desugar_bool("[1, 2, 3].iter().is_sorted_by(|a, b| a.partial_cmp(b))").is_none(),
            "is_sorted_by has an argument; must decline"
        );
    }

    #[test]
    fn from_src_single_element_is_trivially_sorted() {
        // [42].is_sorted() -> Bool(true)
        assert_eq!(desugar_bool("[42].is_sorted()"), Some(true));
    }

    #[test]
    fn from_src_multiple_preserving_adaptors_peel_correctly() {
        // [1, 2, 3].iter().copied().is_sorted() -> Bool(true)
        assert_eq!(
            desugar_bool("[1, 2, 3].iter().copied().is_sorted()"),
            Some(true)
        );
    }
}
