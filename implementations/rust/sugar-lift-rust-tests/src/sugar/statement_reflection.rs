// SPDX-License-Identifier: Apache-2.0
//
// Statement-position compile-time-reflection sugar.

use syn::Expr;

use crate::sugar::claim::SugarRole;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::statement_position;
use crate::{Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::new(
        "statement_reflection",
        SugarRole::StatementEffect,
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    statement_position::reflection_boundary(expr)
        .map(|boundary| Box::new(StatementReflectionSugar { boundary }) as Box<dyn Sugar>)
}

struct StatementReflectionSugar {
    boundary: String,
}

impl Sugar for StatementReflectionSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::Reflection {
            boundary: self.boundary.clone(),
        })
    }
}
