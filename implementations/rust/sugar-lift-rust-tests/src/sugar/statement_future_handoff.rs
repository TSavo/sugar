// SPDX-License-Identifier: Apache-2.0
//
// Statement-position async future handoff sugar.

use syn::Expr;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::statement_position;
use crate::{Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "statement_future_handoff",
    SugarRole::StatementEffect,
    recognize,
);

pub(crate) const COMPOSITE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::composite_before(
    "statement_future_handoff_composite",
    &["runtime_iterator_source"],
    recognize,
);

pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
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
