// SPDX-License-Identifier: Apache-2.0
//
// Statement-position async future handoff sugar.

use syn::Expr;

use crate::sugar::claim::SugarRole;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::statement_position;
use crate::{Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::new(
        "statement_future_handoff",
        SugarRole::StatementEffect,
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    statement_position::future_handoff_boundary(expr)
        .map(|boundary| Box::new(StatementFutureHandoffSugar { boundary }) as Box<dyn Sugar>)
}

struct StatementFutureHandoffSugar {
    boundary: String,
}

impl Sugar for StatementFutureHandoffSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::FutureHandoff {
            boundary: self.boundary.clone(),
        })
    }
}
