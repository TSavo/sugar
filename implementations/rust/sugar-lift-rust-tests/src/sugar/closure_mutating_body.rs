// SPDX-License-Identifier: Apache-2.0
//
// Closure-adaptor mutating body sugar.

use syn::Expr;

use crate::sugar::closure_adaptor;
use crate::sugar::factory::SugarBuildCtx;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON};

/// Mutating body is the conservative verdict owner: Mutation never understates
/// a write effect that an accessor verdict would. This mirrors
/// closure_iter_advance_body, which already comes before mutating_body as the
/// better body owner. Opaque and TLS accessors are mutually exclusive (`with`
/// versus not), so they need no edge between each other; iter_advance_body
/// dominates both transitively.
pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::closure_adaptor_verdict_before(
        "closure_mutating_body",
        &[
            "closure_opaque_accessor",
            "closure_tls_accessor",
            "closure_runtime_receiver",
        ],
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
