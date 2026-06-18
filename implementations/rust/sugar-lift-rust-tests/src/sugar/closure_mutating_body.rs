// SPDX-License-Identifier: Apache-2.0
//
// Closure-adaptor mutating body sugar.

use syn::Expr;

use crate::sugar::claim::{SugarPriority, SugarRole};
use crate::sugar::closure_adaptor;
use crate::sugar::factory::SugarBuildCtx;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::new(
        "closure_mutating_body",
        SugarRole::ClosureAdaptorVerdict,
        SugarPriority::Tertiary,
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let site = closure_adaptor::decompose_closure_adaptor(expr, fcx.let_inits())?;
    site.has_mutating_body()
        .then(|| Box::new(ClosureMutatingBodySugar { site }) as Box<dyn Sugar>)
}

struct ClosureMutatingBodySugar {
    site: closure_adaptor::ClosureAdaptorSite,
}

impl Sugar for ClosureMutatingBodySugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        if self.site.has_mutating_body() {
            return Outcome::Hit(Effect::Mutation {
                boundary: token_key(self.site.expr()),
            });
        }
        Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}
