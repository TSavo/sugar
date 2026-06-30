// SPDX-License-Identifier: Apache-2.0
//
// Statement-position runtime loop-advance sugar.

use crate::sugar::factory::SugarBuildCtx;
use crate::{Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::statement_effect_before(
        "statement_loop_advance",
        &["statement_runtime_expr"],
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    frag.is_loop_advance().then(|| {
        Box::new(StatementLoopAdvanceSugar {
            boundary: frag.token_str(),
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
