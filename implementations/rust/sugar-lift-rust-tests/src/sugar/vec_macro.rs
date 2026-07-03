// SPDX-License-Identifier: Apache-2.0
//
// `VecMacroSugar`: compiler/std macro sugar for literal `vec![a, b, ...]`.
// The repeat form `vec![x; n]` is deliberately not claimed here; array-repeat
// style cardinality is a separate sugar shape.
//
// DEEP MIGRATION (Phase-3 ratchet -- FULLY MIGRATED).
//   * The recognize body uses ONLY SourceFragment typed accessors
//     (`macro_name`, `macro_args_with`, `SugarBody::term_frag`) -- no
//     `as_expr`, no raw `Expr::`/syn field access in the body.
//   * `LiteralAggregateTermSugar` holds `Vec<SugarBody<TermFloor>>` --
//     zero raw syn fields.

use tracing::debug;

use crate::sugar::aggregate_term::LiteralAggregateTermSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "vec_macro",
        crate::sugar::claim::SugarWitnesses::reasoned_bucket(
            "#3415 family b/f: direct, nested, and let-bound vec equality lies are refuted by aggregate/collection decomposition; enrollment remains blocked on owner-correct Pair shape (index probes dispatch to collection owners, format! refuses as runtime arg)",
        ),
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.macro_name()?.as_str() != "vec" {
        return None;
    }
    let mut elems: Vec<SugarBody<TermFloor>> = Vec::new();
    if !frag.macro_args_with(|arg_frag| {
        elems.push(SugarBody::term_frag(&arg_frag, fcx));
    }) {
        return None;
    }
    debug!(
        target: "sugar_lift_rust_tests::sugar::vec_macro",
        len = elems.len(),
        "recognized literal vec macro"
    );
    Some(Box::new(LiteralAggregateTermSugar::new("Vec", elems)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::factory::SugarBuildCtx;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use crate::{
        sugar_ctx, Desugared, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, TemporalPlan,
        TemporalScope,
    };
    use std::collections::BTreeMap;
    use sugar_ir_symbolic::Term;

    /// Navigate to the tail-position expression inside `fn f() { <expr> }`.
    fn macro_frag_from_fn<'a>(file: &'a syn::File) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "test.rs");
        let body = frag.function_body().expect("fn body");
        let stmts = body.statements();
        stmts[0].terms()[0]
    }

    // -- from_src: source string -> SourceFragment -> observed -> build -> floor ----

    /// `vec![1, 2, 3]` is recognized and reduces to a `literal:Vec(...)` Term.
    /// Positive test (recognizer fires; struct holds no raw syn; floor is Complete).
    #[test]
    fn from_src_vec_macro_literal_ints_recognized_and_reduces() {
        let src = r#"fn f() { vec![1, 2, 3] }"#;
        let file = parse_file(src);
        let frag = macro_frag_from_fn(&file);

        // observed: Macro
        assert_eq!(frag.observed(), "Macro");
        // macro_name accessor (no as_expr in recognize body)
        assert_eq!(frag.macro_name().as_deref(), Some("vec"));

        let scope = TemporalScope::new("vec-macro-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &syn::Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let sugar = recognize(&frag, &fcx).expect("vec![1, 2, 3] must be recognized");

        let items: Vec<syn::Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        match sugar.desugar(&ctx) {
            Outcome::Complete(Desugared::Term(term)) => match term.as_ref() {
                Term::Var { name } => {
                    assert!(
                        name.starts_with("literal:Vec("),
                        "expected literal:Vec(...) var, got: {name}"
                    );
                }
                _other => panic!("expected Var(literal:Vec(...)), got unexpected Term variant"),
            },
            _other => panic!("expected Complete(Term), got unexpected Outcome variant"),
        }
    }

    /// A non-vec macro (`format!`) is NOT recognized by `vec_macro`.
    /// Discrimination test: same Macro shape, different name -- must return None.
    #[test]
    fn from_src_non_vec_macro_not_recognized() {
        let src = r#"fn f() { format!("hello") }"#;
        let file = parse_file(src);
        let frag = macro_frag_from_fn(&file);

        assert_eq!(frag.observed(), "Macro");
        assert_ne!(frag.macro_name().as_deref(), Some("vec"));

        let scope = TemporalScope::new("vec-macro-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &syn::Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "format!(...) must not be recognized by vec_macro"
        );
    }

    /// `vec![]` (empty) is recognized and produces a `Vec(...)` aggregate term.
    /// Structural test: zero-element aggregate path.
    #[test]
    fn from_src_empty_vec_macro_recognized_with_zero_elems() {
        let src = r#"fn f() { vec![] }"#;
        let file = parse_file(src);
        let frag = macro_frag_from_fn(&file);

        assert_eq!(frag.observed(), "Macro");
        assert_eq!(frag.macro_name().as_deref(), Some("vec"));

        let scope = TemporalScope::new("vec-macro-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &syn::Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let sugar = recognize(&frag, &fcx).expect("vec![] must be recognized");

        let items: Vec<syn::Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        match sugar.desugar(&ctx) {
            Outcome::Complete(Desugared::Term(term)) => match term.as_ref() {
                Term::Var { name } => {
                    assert!(
                        name.contains("Vec("),
                        "expected Vec(...) aggregate var, got: {name}"
                    );
                }
                _other => panic!("expected Var, got unexpected Term variant"),
            },
            _other => panic!("expected Complete(Term), got unexpected Outcome variant"),
        }
    }
}
