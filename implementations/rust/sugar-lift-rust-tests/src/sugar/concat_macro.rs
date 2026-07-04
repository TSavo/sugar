// SPDX-License-Identifier: MIT OR Apache-2.0
//
// TERM recognizer for closed stdlib `concat!(...)`. The concatenation semantics
// live here, ahead of the generic macro fallback.

use crate::sugar::factory::{build_literal_string_term_node_frag, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "concat_macro",
        &["macro_term", "reference_term"],
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_concat_macro_good() {
                    assert_eq!(concat!("ab", "cd"), "abcd");
                }
            "#,
            r#"
                #[test]
                fn t_concat_macro_bad() {
                    assert_eq!(concat!("ab", "cd"), "abce");
                }
            "#,
        ),
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.strip_refs_groups().macro_name()?.as_str() != "concat" {
        return None;
    }
    Some(build_literal_string_term_node_frag(frag, fcx))
}

#[cfg(test)]
mod tests {
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    fn macro_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        stmts[0].terms()[0]
    }

    /// Positive: `concat!("hello", " ", "world")` -- macro invocation whose
    /// last path segment is "concat".
    /// Proves macro_name() returns "concat" and the accessor emits a plain
    /// String (no raw syn in the struct or recognize body).
    #[test]
    fn from_src_concat_macro_name_is_concat() {
        let src = r#"fn f() -> &'static str { concat!("hello", " ", "world") }"#;
        let file = parse_file(src);
        let frag = macro_expr_frag(&file, "f.rs");

        // observed: the outermost expression is a macro invocation
        assert_eq!(frag.observed(), "Macro");

        // macro_name via typed accessor -- no as_expr / raw Expr:: access
        let name = frag.macro_name().expect("concat! has a macro name");
        assert_eq!(name.as_str(), "concat");

        // The struct field is a plain String, not a syn node.
        assert_eq!(
            name, "concat",
            "macro_name() returns String, not syn::ExprMacro"
        );
    }

    /// Discrimination: `vec!["a"]` has macro_name "vec", not "concat".
    /// Proves macro_name() distinguishes concat! from other macro invocations,
    /// so the guard `macro_name()? == "concat"` correctly rejects vec!.
    #[test]
    fn from_src_vec_macro_name_is_not_concat() {
        let src = r#"fn f() { let _v = vec!["a"]; }"#;
        let file = parse_file(src);
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        // The let statement's initializer is the macro -- reach it via terms()
        let terms = stmts[0].terms();
        let frag = &terms[0];

        assert_eq!(frag.observed(), "Macro");
        let name = frag.macro_name().expect("vec! has a macro name");
        assert_ne!(
            name.as_str(),
            "concat",
            "vec! must not pass the concat! guard"
        );
    }

    /// Structural: a plain string literal is not a macro; macro_name() returns None.
    /// Proves the guard `macro_name()?` short-circuits for non-macro fragments.
    #[test]
    fn from_src_string_literal_macro_name_is_none() {
        let src = r#"fn f() -> &'static str { "hello" }"#;
        let file = parse_file(src);
        let frag = macro_expr_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "PrimitiveLiteral");
        assert!(
            frag.macro_name().is_none(),
            "a string literal has no macro name"
        );
    }
}
