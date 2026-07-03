// SPDX-License-Identifier: Apache-2.0
//
// Statement-position compile-time-reflection sugar.

use crate::sugar::claim::SugarRole;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::new(
        "statement_reflection",
        SugarRole::StatementEffect,
        crate::sugar::claim::SugarWitnesses::Pending,
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let boundary = frag.reflection_boundary_str()?;
    Some(Box::new(StatementReflectionSugar { boundary }))
}

struct StatementReflectionSugar {
    boundary: String,
}

impl Sugar for StatementReflectionSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::Reflection {
            boundary: self.boundary.clone(),
        })
    }
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source string -> SourceFragment -> observed ->
    // reflection_boundary_str -> build StatementReflectionSugar -> assert fields.
    // No parse_quote!, no StubTerm, no run(). The struct holds ONLY a String --
    // zero raw-syn fields -- so these tests prove the migration is clean.
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Navigate to the expression fragment for the first statement in `fn f()`.
    fn match_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        // The match statement is `Stmt::Expr(Expr::Match(..), _)` -> observed "Expr".
        // terms() unwraps the Stmt wrapper and yields the inner Expr::Match fragment.
        let terms = stmts[0].terms();
        terms
            .into_iter()
            .next()
            .expect("match expr in first statement")
    }

    /// from_src: `match TypeId::of::<T>()` with an assertion in an arm -> boundary.
    /// Proves `StatementReflectionSugar` holds `{ boundary: String }` (no raw syn).
    #[test]
    fn from_src_typeid_of_match_with_assert_emits_boundary() {
        let src = r#"
fn f() {
    match TypeId::of::<u32>() {
        _ => { assert!(true); }
    }
}
"#;
        let file = parse_file(src);
        let match_frag = match_expr_frag(&file, "f.rs");

        // observed() is "Match" for an Expr::Match fragment
        assert_eq!(match_frag.observed(), "Match");

        // reflection_boundary_str recognises the TypeId::of scrutinee + assert
        let boundary = match_frag
            .reflection_boundary_str()
            .expect("TypeId::of match with assert -> Some(boundary)");
        assert!(!boundary.is_empty(), "boundary must be non-empty");

        // Build: StatementReflectionSugar holds only String, zero raw-syn fields
        let sugar = StatementReflectionSugar {
            boundary: boundary.clone(),
        };
        assert_eq!(sugar.boundary, boundary);
    }

    /// Discrimination: a plain `match x { .. }` with assert is NOT a reflection boundary.
    /// The scrutinee `x` is a local variable -- no TypeId/Type/info call.
    #[test]
    fn discrimination_plain_match_with_assert_is_not_reflection() {
        let src = r#"
fn f(x: u32) {
    match x {
        0 => { assert!(true); }
        _ => {}
    }
}
"#;
        let file = parse_file(src);
        let match_frag = match_expr_frag(&file, "f.rs");

        assert_eq!(match_frag.observed(), "Match");
        // plain match on a local var: no TypeId/Type/info in scrutinee -> None
        assert!(
            match_frag.reflection_boundary_str().is_none(),
            "plain match on a variable is not a reflection boundary"
        );
    }

    /// Structural: the boundary string contains the scrutinee token text (`TypeId`).
    /// Proves the boundary carries the token representation of the reflection call.
    #[test]
    fn structural_boundary_contains_scrutinee_tokens() {
        let src = r#"
fn f() {
    match TypeId::of::<u32>() {
        _ => { assert!(true); }
    }
}
"#;
        let file = parse_file(src);
        let match_frag = match_expr_frag(&file, "f.rs");
        let boundary = match_frag
            .reflection_boundary_str()
            .expect("TypeId::of match -> reflection boundary");
        // boundary is the token-stream of the scrutinee; must mention TypeId
        assert!(
            boundary.contains("TypeId"),
            "boundary={boundary:?} should contain 'TypeId'"
        );
    }
}
