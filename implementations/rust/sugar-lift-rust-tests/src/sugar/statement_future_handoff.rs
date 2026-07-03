// SPDX-License-Identifier: Apache-2.0
//
// Statement-position async future handoff sugar.

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "statement_future_handoff",
    SugarRole::StatementEffect,
    crate::sugar::claim::SugarWitnesses::reasoned_bucket(
        "future handoff statement effect; no deterministic verdict source",
    ),
    recognize,
);

pub(crate) const COMPOSITE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::composite_before(
    "statement_future_handoff_composite",
    &["runtime_iterator_source"],
    crate::sugar::claim::SugarWitnesses::reasoned_bucket(
        "future handoff composite; no deterministic verdict source",
    ),
    recognize,
);

pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let boundary = frag.future_handoff_boundary()?;
    Some(Box::new(StatementFutureHandoffSugar { boundary }))
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
