// SPDX-License-Identifier: Apache-2.0
//
// ReturnSugar: lifts a tail expression to `Desugared::StmtReturn(term)` and an
// explicit `return <expr>` statement to routeable early-return raise data. The
// caller (BlockSugar / SourceContract routing) then decides whether a surrounding
// handler consumes the early return. Mirrors Python's `ReturnValue(term)` normal
// path plus Phase-2's routeable effect boundary for explicit returns.
//
// Recognized shapes:
//   - `return <expr>;` or `return <expr>` (Stmt::Expr(Expr::Return(Some(e)), _))
//   - tail expression: `Stmt::Expr(expr, None)` where expr is NOT `if` or `block`
//     (those are claimed by IfSugar / BlockSugar respectively).
//
// Desugar: build a TermFloor child body via `SugarBody::term_frag`; desugar time
// calls the body's factory-built Sugar and wraps the resulting Term according to
// the recognized kind. On failure, propagate the `Incomplete(effect)`.

use crate::sugar::claim::StmtSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::route_raises_operation::RouteRaisesOperation;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Effect, Outcome, RaiseEffect, Sugar, SugarCtx};

pub(crate) static STMT_SUGAR: StmtSugarClaim = StmtSugarClaim::statement("return_sugar", recognize);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Arm 1: explicit `return <expr>;` or `return <expr>` (with or without semicolon).
    if let Some(val_frag) = frag.return_value() {
        return Some(Box::new(ReturnSugar {
            boundary: frag.token_str(),
            body: SugarBody::term_frag(&val_frag, fcx),
            kind: ReturnKind::Explicit,
        }));
    }
    // Arm 2: tail expression (no trailing semicolon) that is not a control-flow block.
    // `if`/`block`/`unsafe`/`return` blocks in tail position have their own claims or
    // are excluded by the accessor; ReturnSugar only takes over for "simple" tail values
    // (literals, calls, field accesses, binops, etc.).
    if let Some(tail_frag) = frag.stmt_tail_expr_noncf() {
        return Some(Box::new(ReturnSugar {
            boundary: frag.token_str(),
            body: SugarBody::term_frag(&tail_frag, fcx),
            kind: ReturnKind::Tail,
        }));
    }
    None
}

struct ReturnSugar {
    boundary: String,
    body: SugarBody<TermFloor>,
    kind: ReturnKind,
}

#[derive(Clone, Copy)]
enum ReturnKind {
    Explicit,
    Tail,
}

impl Sugar for ReturnSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.body.desugar(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(term) => match self.kind {
                    ReturnKind::Explicit => {
                        let effect = Effect::Raise(RaiseEffect::EarlyReturnValue {
                            boundary: self.boundary.clone(),
                            value: term,
                        });
                        RouteRaisesOperation::new(Vec::new(), "ReturnSugar")
                            .route_incomplete_with_scope(Outcome::Incomplete(effect), ctx.scope)
                    }
                    ReturnKind::Tail => Outcome::Complete(Desugared::StmtReturn(term)),
                },
                None => panic!(
                    "ReturnSugar body completed a non-Term; the term factory produced a \
                     non-term Desugared where a Term was required"
                ),
            },
            Outcome::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}

#[cfg(test)]
mod from_src_tests {
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    fn first_stmt<'a>(file: &'a syn::File) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "<test>");
        let body = frag.function_body().expect("fn body");
        body.statements().into_iter().next().expect("first stmt")
    }

    /// Positive: `return 42;` is observed as "Return" and return_value() is Some,
    /// confirming the fragment accessor drives the Arm 1 recognize gate.
    #[test]
    fn from_src_explicit_return_is_observed_return_and_has_value() {
        let src = "fn f() -> i32 { return 42; }";
        let file = parse_file(src);
        let frag = first_stmt(&file);

        assert_eq!(
            frag.observed(),
            "Return",
            "explicit return maps to stmt_kind Return"
        );
        assert!(
            frag.return_value().is_some(),
            "return_value() must be Some for `return 42;`"
        );
        assert!(
            frag.stmt_tail_expr_noncf().is_none(),
            "stmt_tail_expr_noncf() must be None for explicit return (Arm 1 owns it)"
        );
    }

    /// Discrimination: bare `return;` (no value) is rejected by both gates --
    /// return_value() yields None (no expr) and stmt_tail_expr_noncf() yields
    /// None (Expr::Return is excluded), so recognize() produces None.
    #[test]
    fn from_src_bare_return_is_rejected_by_both_gates() {
        let src = "fn f() { return; }";
        let file = parse_file(src);
        let frag = first_stmt(&file);

        assert_eq!(frag.observed(), "Return");
        assert!(
            frag.return_value().is_none(),
            "return_value() must be None for bare `return;` (no expr to lift)"
        );
        assert!(
            frag.stmt_tail_expr_noncf().is_none(),
            "stmt_tail_expr_noncf() must be None: Expr::Return is excluded from the tail gate"
        );
    }

    /// Structural: a tail literal `42_i32` has stmt_kind "Expr", return_value()
    /// is None, and stmt_tail_expr_noncf() yields a PrimitiveLiteral child --
    /// exactly what Arm 2 needs to build the body.
    #[test]
    fn from_src_tail_literal_is_noncf_and_yields_primitive_literal_child() {
        let src = "fn f() -> i32 { 42_i32 }";
        let file = parse_file(src);
        let frag = first_stmt(&file);

        assert_eq!(
            frag.observed(),
            "Expr",
            "tail literal stmt is Expr in stmt_kind"
        );
        assert!(
            frag.return_value().is_none(),
            "return_value() must be None for a tail literal (not a Return stmt)"
        );
        let tail = frag
            .stmt_tail_expr_noncf()
            .expect("stmt_tail_expr_noncf() must be Some for tail literal");
        assert_eq!(
            tail.observed(),
            "PrimitiveLiteral",
            "the tail child is a PrimitiveLiteral (Lit::Int)"
        );
    }
}
