// SPDX-License-Identifier: Apache-2.0
//
// Closure-adaptor opaque accessor sugar.

use syn::Expr;

use crate::sugar::closure_adaptor;
use crate::sugar::factory::SugarBuildCtx;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::closure_adaptor_verdict_before(
        "closure_opaque_accessor",
        &["closure_runtime_receiver"],
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let site = closure_adaptor::decompose_closure_adaptor(expr, fcx.let_inits())?;
    site.has_opaque_accessor()
        .then(|| Box::new(ClosureOpaqueAccessorSugar { site }) as Box<dyn Sugar>)
}

struct ClosureOpaqueAccessorSugar {
    site: closure_adaptor::ClosureAdaptorSite,
}

impl Sugar for ClosureOpaqueAccessorSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        if self.site.has_opaque_accessor() {
            return Outcome::Incomplete(Effect::OpaqueRuntime {
                boundary: token_key(self.site.expr()),
                accessor: true,
            });
        }
        Outcome::Incomplete(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}
