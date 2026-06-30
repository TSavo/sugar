// SPDX-License-Identifier: Apache-2.0
//
// Side-effecting `for` statement sugar.
//
// MIGRATION STATUS (Phase-3 ratchet -- FULLY MIGRATED).
//   * `recognize` uses ONLY `SourceFragment::for_loop_mutation_boundary(fcx)` --
//     no `as_expr()` shim, no raw `Expr::` match, no raw syn imports.
//   * The Sugar struct holds only `String` (no raw syn).

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::{Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::composite_before("for_loop_mutation", &["forall_loop"], recognize);

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let boundary = frag.for_loop_mutation_boundary(fcx)?;
    Some(Box::new(ForLoopMutationSugar { boundary }))
}

struct ForLoopMutationSugar {
    boundary: String,
}

impl Sugar for ForLoopMutationSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::Mutation {
            boundary: self.boundary.clone(),
        })
    }
}
