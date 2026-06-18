// SPDX-License-Identifier: Apache-2.0
//
// Statement-position runtime loop-advance sugar.

use syn::Expr;

use crate::sugar::claim::{SugarPriority, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::statement_position;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::new(
        "statement_loop_advance",
        SugarRole::StatementEffect,
        SugarPriority::Tertiary,
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    statement_position::has_loop_advance(expr)
        .then(|| Box::new(StatementLoopAdvanceSugar { expr: expr.clone() }) as Box<dyn Sugar>)
}

struct StatementLoopAdvanceSugar {
    expr: Expr,
}

impl Sugar for StatementLoopAdvanceSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        if statement_position::has_loop_advance(&self.expr) {
            return Outcome::Hit(Effect::LoopAdvance {
                boundary: token_key(&self.expr),
            });
        }
        Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}
