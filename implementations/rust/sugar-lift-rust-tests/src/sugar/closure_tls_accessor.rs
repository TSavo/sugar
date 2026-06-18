// SPDX-License-Identifier: Apache-2.0
//
// Closure-adaptor thread-local accessor sugar.

use syn::Expr;

use crate::sugar::closure_adaptor;
use crate::sugar::factory::SugarBuildCtx;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::closure_adaptor_verdict("closure_tls_accessor", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let site = closure_adaptor::decompose_closure_adaptor(expr, fcx.let_inits())?;
    site.has_tls_accessor()
        .then(|| Box::new(ClosureTlsAccessorSugar { site }) as Box<dyn Sugar>)
}

struct ClosureTlsAccessorSugar {
    site: closure_adaptor::ClosureAdaptorSite,
}

impl Sugar for ClosureTlsAccessorSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        if self.site.has_tls_accessor() {
            return Outcome::Hit(Effect::Tls {
                boundary: token_key(self.site.expr()),
            });
        }
        Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}
