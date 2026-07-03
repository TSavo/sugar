// SPDX-License-Identifier: Apache-2.0
//
// Atomic `.load(..)` over a non-path receiver is a runtime state boundary.

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "atomic_load",
    &["method"],
    crate::sugar::claim::SugarWitnesses::Pending,
    recognize,
);

pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // `is_atomic_load_method` checks: MethodCall + method=="load" + 1 arg
    // + receiver is NOT a simple local-ident path. No raw-syn escape.
    if !frag.is_atomic_load_method() {
        return None;
    }
    Some(Box::new(AtomicLoadSugar {
        boundary: frag.token_str(),
    }))
}

struct AtomicLoadSugar {
    boundary: String,
}

impl Sugar for AtomicLoadSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::AtomicLoad {
            boundary: self.boundary.clone(),
        })
    }
}
