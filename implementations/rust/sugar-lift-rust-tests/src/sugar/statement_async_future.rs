// SPDX-License-Identifier: Apache-2.0
//
// Statement-position dormant async-future sugar.
//
// `let fut = async { assert_ok!(...) };` constructs a future. It does not execute the
// assertion vocabulary inside that future at the `let` site. The assertion becomes
// meaningful only when a driver consumes the future (`join!`, `spawn`, `block_on`, ...),
// and those driver semantics must be learned from source/proof. This sugar owns the
// factory-level accounting for the dormant construction so it does not fall into the
// generic let-initializer bucket.
//
// MIGRATION STATUS (Phase-3 ratchet -- FULLY MIGRATED).
//   * `recognize` uses ONLY `SourceFragment::is_async_with_asserts()` and
//     `SourceFragment::token_str()` -- no `as_expr()` shim, no raw `Expr::` access.
//   * `StatementAsyncFutureSugar` holds `boundary: String` -- zero raw-syn fields.

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::statement_effect("statement_async_future", recognize);

pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // `is_async_with_asserts()` checks Expr::Async + count_asserts_in_stmts > 0.
    if !frag.is_async_with_asserts() {
        return None;
    }
    Some(Box::new(StatementAsyncFutureSugar {
        boundary: frag.token_str(),
    }))
}

struct StatementAsyncFutureSugar {
    boundary: String,
}

impl Sugar for StatementAsyncFutureSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::DormantFuture {
            boundary: self.boundary.clone(),
        })
    }
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source string -> SourceFragment -> assert observed ->
    // build StatementAsyncFutureSugar from fragment-derived data -> assert fields.
    // No parse_quote!, no StubTerm, no run(). The struct holds ONLY a String --
    // zero raw-syn fields -- so these tests prove the migration is clean.
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    fn async_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        // async expr as a statement-expression; terms() yields the inner Expr::Async
        let terms = stmts[0].terms();
        terms.into_iter().next().expect("async expr in body")
    }

    /// Positive: `async { assert!(x) }` -> is_async_with_asserts() == true,
    /// boundary is a non-empty String containing "async". Proves struct holds
    /// only `boundary: String` -- no raw-syn field.
    #[test]
    fn from_src_async_with_assert_recognized() {
        let file = parse_file("fn f(x: bool) { async { assert!(x) }; }");
        let frag = async_expr_frag(&file, "f.rs");

        // The async expr lands in the Other:Expr: parametric bucket
        assert!(
            frag.observed().contains("Async"),
            "expected observed to contain Async, got: {}",
            frag.observed()
        );

        // accessor confirms assertion surface present
        assert!(frag.is_async_with_asserts());

        // token_str() gives the boundary -- no raw-syn escape
        let boundary = frag.token_str();
        assert!(!boundary.is_empty(), "boundary must not be empty");
        assert!(
            boundary.contains("async"),
            "boundary should contain 'async': {boundary}"
        );

        // Build: struct holds only a String (the migration invariant)
        let sugar = StatementAsyncFutureSugar {
            boundary: boundary.clone(),
        };
        assert_eq!(sugar.boundary, boundary);
    }

    /// Discrimination: `async { let _x = 1; }` (no assertion) must NOT be recognized.
    /// Proves is_async_with_asserts() returns false when block has no assertion surface.
    #[test]
    fn discrimination_async_without_assert_not_recognized() {
        let file = parse_file("fn f() { async { let _x = 1; }; }");
        let frag = async_expr_frag(&file, "f.rs");
        assert!(
            frag.observed().contains("Async"),
            "expected Async observed: {}",
            frag.observed()
        );
        assert!(!frag.is_async_with_asserts());
    }

    /// Structural: a non-async fragment (`PrimitiveLiteral`) returns false from
    /// is_async_with_asserts(). Proves the guard does not fire on wrong shapes.
    #[test]
    fn structural_non_async_fragment_returns_false() {
        let file = parse_file("fn f() -> i32 { 42 }");
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = fn_frag.function_body().unwrap();
        let terms = body.statements()[0].terms();
        let lit_frag = &terms[0];

        assert_eq!(lit_frag.observed(), "PrimitiveLiteral");
        assert!(!lit_frag.is_async_with_asserts());
    }
}
