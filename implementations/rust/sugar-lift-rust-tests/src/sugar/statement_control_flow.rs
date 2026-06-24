// SPDX-License-Identifier: Apache-2.0
//
// Statement-position future-continuation sugar.

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::statement_position;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::statement_effect("statement_control_flow", recognize);

pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    statement_position::has_control_flow(expr).then(|| {
        Box::new(StatementControlFlowSugar {
            boundary: token_key(expr),
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
