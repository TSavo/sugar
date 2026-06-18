// SPDX-License-Identifier: Apache-2.0
//
// Closure-adaptor runtime receiver sugar.

use syn::Expr;

use crate::sugar::claim::{SugarPriority, SugarRole};
use crate::sugar::closure_adaptor;
use crate::sugar::factory::SugarBuildCtx;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::new(
        "closure_runtime_receiver",
        SugarRole::ClosureAdaptorVerdict,
        SugarPriority::Quaternary,
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let site = closure_adaptor::decompose_closure_adaptor(expr, fcx.let_inits())?;
    site.has_runtime_receiver(fcx.scope())
        .then(|| Box::new(ClosureRuntimeReceiverSugar { site }) as Box<dyn Sugar>)
}

struct ClosureRuntimeReceiverSugar {
    site: closure_adaptor::ClosureAdaptorSite,
}

impl Sugar for ClosureRuntimeReceiverSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if self.site.has_runtime_receiver(ctx.scope) {
            return Outcome::Hit(Effect::OpaqueRuntime {
                boundary: token_key(self.site.expr()),
                accessor: false,
            });
        }
        Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}
