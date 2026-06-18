// SPDX-License-Identifier: Apache-2.0
//
// Statement-position mutably-aliased runtime expression sugar.

use syn::Expr;

use crate::sugar::claim::{SugarPriority, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::statement_position;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::new(
        "statement_runtime_expr",
        SugarRole::StatementEffect,
        SugarPriority::Quaternary,
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    statement_position::has_runtime_expr(expr)
        .then(|| Box::new(StatementRuntimeExprSugar { expr: expr.clone() }) as Box<dyn Sugar>)
}

struct StatementRuntimeExprSugar {
    expr: Expr,
}

impl Sugar for StatementRuntimeExprSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        if statement_position::has_runtime_expr(&self.expr) {
            return Outcome::Hit(Effect::RuntimeExprStmt {
                boundary: token_key(&self.expr),
            });
        }
        Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}
