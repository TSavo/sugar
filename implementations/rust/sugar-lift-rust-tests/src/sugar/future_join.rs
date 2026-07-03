// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for std `future::join!`.
//
// `join!` is a future-producing std macro, not a source-visible `macro_rules!`
// body this lifter owns. This sugar claims the macro before the generic macro
// fallback so the boundary is typed as future construction instead of becoming
// a macro-expansion construction gap.

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "future_join",
    &["macro_term"],
    crate::sugar::claim::SugarWitnesses::reasoned_bucket(
        "async future join runtime handoff; no stable verdict witness yet",
    ),
    recognize,
);

pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    (frag.macro_name().as_deref() == Some("join")).then(|| {
        Box::new(FutureJoinSugar {
            boundary: frag.token_str(),
        }) as Box<dyn Sugar>
    })
}

struct FutureJoinSugar {
    boundary: String,
}

impl Sugar for FutureJoinSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::FutureJoin {
            boundary: self.boundary.clone(),
        })
    }
}
