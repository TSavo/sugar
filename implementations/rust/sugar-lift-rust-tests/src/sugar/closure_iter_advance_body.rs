// SPDX-License-Identifier: Apache-2.0
//
// Closure-adaptor captured-iterator advance sugar.

use syn::Expr;

use crate::sugar::closure_adaptor;
use crate::sugar::factory::SugarBuildCtx;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::closure_adaptor_verdict_before(
        "closure_iter_advance_body",
        &["closure_mutating_body", "closure_runtime_receiver"],
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let site = closure_adaptor::decompose_closure_adaptor(expr, fcx.let_inits())?;
    site.has_iter_advance_body()
        .then(|| Box::new(ClosureIterAdvanceBodySugar { site }) as Box<dyn Sugar>)
}

struct ClosureIterAdvanceBodySugar {
    site: closure_adaptor::ClosureAdaptorSite,
}

impl Sugar for ClosureIterAdvanceBodySugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        if self.site.has_iter_advance_body() {
            return Outcome::Hit(Effect::IterAdvance {
                boundary: token_key(self.site.expr()),
            });
        }
        Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}
