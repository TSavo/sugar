// SPDX-License-Identifier: Apache-2.0
//
// Statement-position assertion syntax that appears inside a value expression.
// The assertion macro is the source boundary: it is not an unconditional
// top-level point-wise assertion surface in this role. Enclosing block / closure
// sugars only bubble this named effect.

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::{Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "statement_nested_assertion",
    SugarRole::StatementEffect,
    recognize,
);

pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    frag.is_assertion_surface_macro().then(|| {
        Box::new(StatementNestedAssertionSugar {
            boundary: frag.token_str(),
        }) as Box<dyn Sugar>
    })
}

struct StatementNestedAssertionSugar {
    boundary: String,
}

impl Sugar for StatementNestedAssertionSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::NestedAssertionValue {
            boundary: self.boundary.clone(),
        })
    }
}
