// SPDX-License-Identifier: Apache-2.0
//
// Sugar for unsafe-memory writes. `clone_to_uninit` mutates raw / MaybeUninit
// storage, so a value flowing through it is not a timeless construction from
// source literals. The method call owns the typed boundary; enclosing blocks only
// bubble this effect.

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("unsafe_memory", SugarRole::Term, recognize);

pub(crate) const STATEMENT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "statement_unsafe_memory",
    SugarRole::StatementEffect,
    recognize,
);

pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if !frag.call_is_method_call() {
        return None;
    }
    if frag.call_target_name().as_deref() != Some("clone_to_uninit") {
        return None;
    }
    Some(Box::new(UnsafeMemorySugar {
        boundary: frag.token_str(),
    }))
}

struct UnsafeMemorySugar {
    boundary: String,
}

impl Sugar for UnsafeMemorySugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::RuntimeExprStmt {
            boundary: self.boundary.clone(),
        })
    }
}
