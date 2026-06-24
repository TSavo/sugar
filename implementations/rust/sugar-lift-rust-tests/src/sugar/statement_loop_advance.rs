// SPDX-License-Identifier: Apache-2.0
//
// Statement-position runtime loop-advance sugar.

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::statement_position;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::statement_effect_before(
        "statement_loop_advance",
        &["statement_runtime_expr"],
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    statement_position::has_loop_advance(expr).then(|| {
        Box::new(StatementLoopAdvanceSugar {
            boundary: token_key(expr),
        }) as Box<dyn Sugar>
    })
}

struct StatementLoopAdvanceSugar {
    boundary: String,
}

impl Sugar for StatementLoopAdvanceSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::LoopAdvance {
            boundary: self.boundary.clone(),
        })
    }
}
