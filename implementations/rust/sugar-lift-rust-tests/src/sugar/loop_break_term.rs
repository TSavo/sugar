// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for the value-transparent `loop { break expr; }` shape.

use syn::{Expr, Stmt};

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::{Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("loop_break_term", recognize);

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Loop(loop_expr) = expr else {
        return None;
    };
    let payload = single_break_payload(loop_expr.body.stmts.as_slice())?;
    Some(Box::new(LoopBreakTermSugar {
        payload: SugarBody::term(payload, fcx),
    }))
}

struct LoopBreakTermSugar {
    payload: SugarBody<TermFloor>,
}

impl Sugar for LoopBreakTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.payload.desugar(ctx)
    }
}

fn single_break_payload(stmts: &[Stmt]) -> Option<&Expr> {
    let [Stmt::Expr(Expr::Break(expr_break), _)] = stmts else {
        return None;
    };
    if expr_break.label.is_some() {
        return None;
    }
    expr_break.expr.as_deref()
}
