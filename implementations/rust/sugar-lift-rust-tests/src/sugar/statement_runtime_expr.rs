// SPDX-License-Identifier: Apache-2.0
//
// Statement-position mutably-aliased runtime expression sugar.

use syn::Expr;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::statement_position;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "statement_runtime_expr",
    SugarRole::StatementEffect,
    recognize_statement_effect,
);

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::fallback_constraint("constraint_runtime_expr", recognize_constraint);

pub(crate) fn recognize_statement_effect(
    expr: &Expr,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    if fcx.scope().temporal_rewrite_can_apply(expr) {
        return None;
    }
    statement_position::has_runtime_expr(expr)
        .then(|| Box::new(StatementRuntimeExprSugar { expr: expr.clone() }) as Box<dyn Sugar>)
}

pub(crate) fn recognize_constraint(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if fcx.scope().temporal_rewrite_can_apply(expr) {
        return None;
    }
    statement_position::is_runtime_mutation_statement(expr)
        .then(|| Box::new(StatementRuntimeExprSugar { expr: expr.clone() }) as Box<dyn Sugar>)
}

struct StatementRuntimeExprSugar {
    expr: Expr,
}

impl Sugar for StatementRuntimeExprSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        if statement_position::has_runtime_boundary(&self.expr) {
            return Outcome::Incomplete(Effect::RuntimeExprStmt {
                boundary: token_key(&self.expr),
            });
        }
        Outcome::Incomplete(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}
