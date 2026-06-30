// SPDX-License-Identifier: Apache-2.0
//
// ReturnSugar: lifts a `return <expr>` statement or a tail expression to
// `Desugared::StmtReturn(term)`. The caller (BlockSugar) then places this into the
// guarded-return composition. Mirrors Python's `ReturnValue(term)` production from
// `ReturnSugar`.
//
// Recognized shapes:
//   - `return <expr>;` or `return <expr>` (Stmt::Expr(Expr::Return(Some(e)), _))
//   - tail expression: `Stmt::Expr(expr, None)` where expr is NOT `if` or `block`
//     (those are claimed by IfSugar / BlockSugar respectively).
//
// Desugar: translate `expr` via `translate_term_in_scope` using `ctx.scope` (which
// BlockSugar has already set to the correct post-BoundVar scope for this statement
// position). On failure, propagate the `Incomplete(effect)`.

use syn::{Expr, Stmt};

use crate::sugar::claim::StmtSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::term_dispatch::translate_term_in_scope;
use crate::{Desugared, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) static STMT_SUGAR: StmtSugarClaim = StmtSugarClaim::statement("return_sugar", recognize);

fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let stmt = frag.as_stmt()?;
    match stmt {
        // Explicit `return <expr>;` or `return <expr>` (with or without semicolon).
        Stmt::Expr(Expr::Return(ret), _) => {
            let raw_return = ret.expr.as_deref()?.clone();
            Some(Box::new(ReturnSugar { raw_return }))
        }
        // Tail expression (no trailing semicolon). `if`/`block`/`unsafe` blocks in
        // tail position have their own claims; ReturnSugar only takes over for
        // "simple" tail values (literals, calls, field accesses, binops, etc.).
        Stmt::Expr(tail_expr, None)
            if !matches!(tail_expr, Expr::If(_) | Expr::Block(_) | Expr::Unsafe(_)) =>
        {
            Some(Box::new(ReturnSugar { raw_return: tail_expr.clone() }))
        }
        _ => None,
    }
}

struct ReturnSugar {
    raw_return: Expr,
}

impl Sugar for ReturnSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match translate_term_in_scope(&self.raw_return, ctx.scope) {
            Ok(term) => Outcome::Complete(Desugared::StmtReturn(term)),
            Err(effect) => Outcome::Incomplete(effect),
        }
    }
}
