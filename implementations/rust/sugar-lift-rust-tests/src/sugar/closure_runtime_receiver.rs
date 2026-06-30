// SPDX-License-Identifier: Apache-2.0
//
// Closure-adaptor runtime receiver sugar.

use crate::sugar::claim::SugarRole;
use crate::sugar::closure_adaptor;
use crate::sugar::factory::SugarBuildCtx;
use crate::{Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::new(
        "closure_runtime_receiver",
        SugarRole::ClosureAdaptorVerdict,
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let site = closure_adaptor::decompose_closure_adaptor_frag(frag, fcx.let_inits(), fcx.scope())?;
    site.has_runtime_receiver(fcx.scope())
        .then(|| Box::new(ClosureRuntimeReceiverSugar { site }) as Box<dyn Sugar>)
}

struct ClosureRuntimeReceiverSugar {
    site: closure_adaptor::ClosureAdaptorSite,
}

impl Sugar for ClosureRuntimeReceiverSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if self.site.has_runtime_receiver(ctx.scope) {
            return Outcome::Incomplete(Effect::OpaqueRuntime {
                boundary: self.site.boundary().to_owned(),
                accessor: false,
            });
        }
        closure_runtime_receiver_gap("recognized site no longer has a runtime receiver")
    }
}

fn closure_runtime_receiver_gap(reason: &str) -> ! {
    panic!("closure_runtime_receiver did not reach a lawful floor: {reason}")
}
