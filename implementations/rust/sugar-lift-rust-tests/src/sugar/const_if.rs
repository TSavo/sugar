// SPDX-License-Identifier: MIT OR Apache-2.0
//
// TERM recognizer for a CONSTANT `if cond { .. } else { .. }` expression
// (`Expr::If`) in term position. When the condition and the taken branch
// const-fold to a closed scalar value, the whole conditional collapses to that
// ground value -- the SAME `const_eval` + `const_val_term` path `binop` uses for a
// const arithmetic/comparison expression, so the emitted term is sort-identical to
// the literal the source would otherwise have written.
//
// SOUNDNESS: `const_eval` computes the EXACT compile-time bool of the condition and
// selects exactly the branch Rust evaluates; the untaken branch is dead. A non-const
// condition / taken branch, or an else-less `if`, folds to None here, so this Sugar
// DECLINES (returns `None`) and the conditional stays unresolved -- finite-or-refuse,
// never a fake-fold. No other Term-role recognizer claims `Expr::If`, so this is the
// sole `Expr::If` claimant (no catalog ambiguity).
//
// MIGRATION STATUS (Phase-3 ratchet -- FULLY MIGRATED).
//   * `recognize` uses ONLY `SourceFragment::const_folded_if_term()` -- no
//     `as_expr()` shim, no raw `Expr::` match, no raw `syn` imports.
//   * The Sugar struct is `ResolvedTermSugar` from `term_leaf` (holds `Rc<Term>`,
//     no raw syn).

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_leaf::resolved_term;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "const_if",
        &["value_if"],
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_const_if_then_good() {
                    assert!((if 'a' as u32 <= 98 && 98 <= 'z' as u32 { 98 + 'A' as u32 - 'a' as u32 } else { 98 }) == 66);
                }
            "#,
            r#"
                #[test]
                fn t_const_if_then_bad() {
                    assert!((if 'a' as u32 <= 98 && 98 <= 'z' as u32 { 98 + 'A' as u32 - 'a' as u32 } else { 98 }) == 67);
                }
            "#,
        ),
        recognize,
    );

/// TERM recognizer for a const `Expr::If`. Folds the whole conditional to its taken
/// branch's ground value via `SourceFragment::const_folded_if_term`; declines
/// (`None`) for any non-`If` fragment or any `If` that is not a closed constant.
/// Zero raw-syn access in this body.
pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let term = frag.const_folded_if_term()?;
    Some(resolved_term(term))
}

#[cfg(test)]
mod tests {
    // Phase-3 TDD harness: source string -> SourceFragment -> observed ->
    // const_folded_if_term() -> assert Term shape.
    // No parse_quote!, no StubTerm, no run().
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use sugar_ir_symbolic::{ConstValue, Term};

    /// Navigate to the first (tail) expression in a one-liner fn body.
    fn tail_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("body");
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    /// A const-foldable `if 1 > 0 { 42 } else { 0 }` yields `num(42)`.
    #[test]
    fn from_src_const_if_true_branch_folds_to_term() {
        let src = "fn f() -> i32 { if 1 > 0 { 42 } else { 0 } }";
        let file = parse_file(src);
        let if_frag = tail_expr_frag(&file, "f.rs");

        // observed: the fragment is an If node
        assert_eq!(if_frag.observed(), "If");

        // build: const_folded_if_term returns Some without as_expr / raw Expr::
        let term = if_frag
            .const_folded_if_term()
            .expect("1 > 0 is const true; then-branch 42 must fold");

        // floor: condition true -> taken branch 42 = num(42)
        match &*term {
            Term::Const {
                value: ConstValue::Int(v),
                ..
            } => {
                assert_eq!(*v, 42, "expected 42 from then-branch");
            }
            other => panic!("expected Int const 42, got {other:?}"),
        }
    }

    /// Else branch is selected when condition is false:
    /// `if 0 > 1 { 99 } else { 7 }` -> `num(7)`.
    #[test]
    fn from_src_const_if_false_branch_folds_to_term() {
        let src = "fn f() -> i32 { if 0 > 1 { 99 } else { 7 } }";
        let file = parse_file(src);
        let if_frag = tail_expr_frag(&file, "f.rs");

        assert_eq!(if_frag.observed(), "If");

        let term = if_frag
            .const_folded_if_term()
            .expect("0 > 1 is const false; else-branch 7 must fold");
        match &*term {
            Term::Const {
                value: ConstValue::Int(v),
                ..
            } => {
                assert_eq!(*v, 7, "expected 7 from else-branch");
            }
            other => panic!("expected Int const 7, got {other:?}"),
        }
    }

    /// A runtime condition (variable) must decline -- no fake-fold.
    #[test]
    fn from_src_runtime_condition_declines() {
        let src = "fn f(x: bool) -> i32 { if x { 1 } else { 0 } }";
        let file = parse_file(src);
        let if_frag = tail_expr_frag(&file, "f.rs");

        assert_eq!(if_frag.observed(), "If");
        assert!(
            if_frag.const_folded_if_term().is_none(),
            "runtime condition must yield None"
        );
    }

    /// A non-If fragment (BinOp) must return None from const_folded_if_term.
    #[test]
    fn from_src_non_if_returns_none() {
        let src = "fn f() -> i32 { 1 + 2 }";
        let file = parse_file(src);
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = frag.function_body().expect("body");
        let terms = body.statements()[0].terms();
        let binop = &terms[0];

        assert_eq!(binop.observed(), "BinOp");
        assert!(
            binop.const_folded_if_term().is_none(),
            "BinOp is not an If; must yield None"
        );
    }
}
