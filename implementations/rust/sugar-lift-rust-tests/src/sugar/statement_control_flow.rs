// SPDX-License-Identifier: Apache-2.0
//
// Statement-position future-continuation sugar.
//
// MIGRATION STATUS (Phase-3 ratchet -- FULLY MIGRATED).
//   * `recognize` uses ONLY `SourceFragment::has_control_flow()` and
//     `SourceFragment::token_str()` -- no shim call, no raw `Expr::` access.
//   * `StatementControlFlowSugar` holds `boundary: String` -- zero raw-syn fields.

use crate::sugar::factory::SugarBuildCtx;
use crate::{Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::statement_effect("statement_control_flow", recognize);

pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // `has_control_flow()` checks: carries an assertion macro AND contains `.await`
    // (both visible to the syn visitor at the expression level), without escaping
    // to raw syn via the shim accessor.
    frag.has_control_flow().then(|| {
        Box::new(StatementControlFlowSugar {
            boundary: frag.token_str(),
        }) as Box<dyn Sugar>
    })
}

struct StatementControlFlowSugar {
    boundary: String,
}

impl Sugar for StatementControlFlowSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::ControlFlow {
            boundary: self.boundary.clone(),
        })
    }
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source string -> SourceFragment -> assert observed ->
    // has_control_flow() -> build StatementControlFlowSugar -> assert fields.
    // No parse_quote!, no StubTerm, no run(). The struct holds ONLY a String --
    // zero raw-syn fields -- so these tests prove the migration is clean.
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Navigate to the expression fragment for the first statement in `fn f()`.
    /// Requires the statement to be `Stmt::Expr(e, _)` (tail or semicoloned expr).
    fn first_stmt_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        // Use terms() to unwrap the Stmt::Expr wrapper and yield the inner expression.
        let terms = stmts[0].terms();
        terms.into_iter().next().expect("expression in first statement")
    }

    /// from_src: an `if` whose condition is `.await` and whose branch contains
    /// `assert!` -- `carries_assert` AND `expr_contains_await` both fire at the
    /// syn expression level, so `has_control_flow()` returns true.
    ///
    /// Both the `.await` (in the `if` condition) and `assert!` (in the then-branch)
    /// are visible to the syn recursive visitor, unlike macros whose token streams
    /// are opaque. `token_str()` over the whole `if` is the floor boundary.
    #[test]
    fn from_src_if_await_cond_with_assert_branch_is_control_flow() {
        let src = "fn f() { if some_future().await { assert!(true) } }";
        let file = parse_file(src);
        let frag = first_stmt_expr_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "If");
        assert!(
            frag.has_control_flow(),
            "if <await-cond> {{ assert!(..) }} must be recognised as control-flow"
        );
        // Floor: boundary is the token-stream string of the whole if expression.
        let boundary = frag.token_str();
        assert!(
            boundary.contains("await"),
            "boundary must contain the await: {boundary}"
        );
        assert!(
            boundary.contains("assert"),
            "boundary must contain the assert: {boundary}"
        );
        // Build: struct holds only a String (the migration invariant).
        let sugar = StatementControlFlowSugar { boundary: boundary.clone() };
        assert_eq!(sugar.boundary, boundary);
    }

    /// Discrimination: a plain binary expression has no assertion and no await --
    /// `has_control_flow()` returns false.
    #[test]
    fn discrimination_plain_binop_is_not_control_flow() {
        let src = "fn f() -> i32 { 1 + 2 }";
        let file = parse_file(src);
        let frag = first_stmt_expr_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "BinOp");
        assert!(
            !frag.has_control_flow(),
            "plain binary expression must NOT be control-flow"
        );
    }

    /// Structural: an `if` expression whose condition is NOT `.await` (no await) does
    /// not trigger `has_control_flow()`, even if the branch contains `assert!`.
    #[test]
    fn structural_if_without_await_is_not_control_flow() {
        let src = "fn f(x: bool) { if x { assert!(true) } }";
        let file = parse_file(src);
        let frag = first_stmt_expr_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "If");
        assert!(
            !frag.has_control_flow(),
            "if without .await must NOT be control-flow even with assert in branch"
        );
    }
}
