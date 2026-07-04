// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Closure-adaptor thread-local accessor sugar.

use crate::sugar::closure_adaptor;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::closure_adaptor_verdict_before(
        "closure_tls_accessor",
        &["closure_runtime_receiver"],
        crate::sugar::claim::SugarWitnesses::reasoned_bucket(
            "thread-local closure accessor; runtime TLS state is not verdict-bearing yet",
        ),
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let site = closure_adaptor::decompose_closure_adaptor_frag(frag, fcx.let_inits(), fcx.scope())?;
    site.has_tls_accessor()
        .then(|| Box::new(ClosureTlsAccessorSugar) as Box<dyn Sugar>)
}

struct ClosureTlsAccessorSugar;

impl Sugar for ClosureTlsAccessorSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::Tls)
    }
}
