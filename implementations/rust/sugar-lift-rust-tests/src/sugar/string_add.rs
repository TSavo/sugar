// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for closed string `+`. Numeric and otherwise unresolved `+`
// expressions decline to the generic BinOpSugar fallback.

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::format::{build_literal_string_term_node_frag, is_factory_string_add_shape_frag};
use crate::sugar::source_fragment::SourceFragment;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "string_add",
        &["binop"],
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_string_add_good() {
                    assert_eq!("ab".to_string() + "cd", "abcd");
                }
            "#,
            r#"
                #[test]
                fn t_string_add_bad() {
                    assert_eq!("ab".to_string() + "cd", "abce");
                }
            "#,
        ),
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if !is_factory_string_add_shape_frag(frag, fcx) {
        return None;
    }
    Some(build_literal_string_term_node_frag(frag, fcx))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    fn string_add_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        // The tail expression statement is the only statement;
        // `terms()` on the Expr stmt yields the single BinOp expr child.
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive: `"hello" + " world"` is classified as `"BinOp"`, `binop_op_kind()` returns
    /// `"Add"`, left and right operands are both `"PrimitiveLiteral"` string literals.
    /// Proves the typed accessors carry the string-add shape without raw syn.
    #[test]
    fn from_src_string_add_observed_and_operands() {
        let file = parse_file(r#"fn f() { "hello" + " world" }"#);
        let binop = string_add_expr_frag(&file, "f.rs");

        // observed shape
        assert_eq!(binop.observed(), "BinOp");

        // op kind via typed accessor (no as_expr / Expr:: / Binary field access here)
        assert_eq!(binop.binop_op_kind(), Some("Add"));

        // left operand: a string literal
        let left = binop.binop_left().expect("left operand present");
        assert_eq!(left.observed(), "PrimitiveLiteral");

        // right operand: also a string literal
        let right = binop.binop_right().expect("right operand present");
        assert_eq!(right.observed(), "PrimitiveLiteral");
    }

    /// Discrimination: `a + b` where both operands are name-paths (numeric add) has the
    /// same `"BinOp"` / `"Add"` shape, but `binop_left()` returns `"Name"` not
    /// `"PrimitiveLiteral"` — proves the accessor distinguishes string-add from numeric add.
    #[test]
    fn discrimination_numeric_add_operands_are_names_not_string_literals() {
        let file = parse_file("fn f(a: i32, b: i32) -> i32 { a + b }");
        let binop = string_add_expr_frag(&file, "f.rs");

        assert_eq!(binop.observed(), "BinOp");
        assert_eq!(binop.binop_op_kind(), Some("Add"));

        // operands are Names, not PrimitiveLiteral — not a string-add shape
        let left = binop.binop_left().expect("left present");
        assert_eq!(left.observed(), "Name");
        let right = binop.binop_right().expect("right present");
        assert_eq!(right.observed(), "Name");
    }

    /// Structural: a `MethodCall` fragment returns `None` from `binop_op_kind()`,
    /// `binop_left()`, and `binop_right()` — the binop accessors are shape-specific
    /// and do not bleed across expression kinds.
    #[test]
    fn structural_method_call_returns_none_from_binop_accessors() {
        let file = parse_file(r#"fn f(s: &str) -> String { s.to_string() }"#);
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        let terms = stmts[0].terms();
        let call = &terms[0];

        assert_eq!(call.observed(), "MethodCall");
        assert_eq!(call.binop_op_kind(), None);
        assert!(call.binop_left().is_none());
        assert!(call.binop_right().is_none());
    }
}
