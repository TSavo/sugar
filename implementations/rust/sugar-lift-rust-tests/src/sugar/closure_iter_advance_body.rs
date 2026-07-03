// SPDX-License-Identifier: Apache-2.0
//
// Closure-adaptor captured-iterator advance sugar.

use crate::sugar::closure_adaptor;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::closure_adaptor_verdict_before(
        "closure_iter_advance_body",
        &["closure_mutating_body", "closure_runtime_receiver"],
        crate::sugar::claim::SugarWitnesses::reasoned_bucket(
            "closure adaptor runtime iterator advance; needs closure-state witness machinery",
        ),
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let site = closure_adaptor::decompose_closure_adaptor_frag(frag, fcx.let_inits(), fcx.scope())?;
    site.has_iter_advance_body()
        .then(|| Box::new(ClosureIterAdvanceBodySugar { site }) as Box<dyn Sugar>)
}

struct ClosureIterAdvanceBodySugar {
    site: closure_adaptor::ClosureAdaptorSite,
}

impl Sugar for ClosureIterAdvanceBodySugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::IterAdvance {
            boundary: self.site.boundary().to_owned(),
        })
    }
}
