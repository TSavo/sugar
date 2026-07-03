// SPDX-License-Identifier: Apache-2.0
//
// Statement-position mutably-aliased runtime expression sugar.

use syn::Expr;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::statement_position;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "statement_runtime_expr",
    SugarRole::StatementEffect,
    crate::sugar::claim::SugarWitnesses::reasoned_bucket(
        "runtime expression statement; no stable value source in witness harness",
    ),
    recognize_statement_effect,
);

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::fallback_constraint(
    "constraint_runtime_expr",
    crate::sugar::claim::SugarWitnesses::reasoned_bucket(
        "runtime-expression constraint; needs runtime value witness machinery",
    ),
    recognize_constraint,
);

pub(crate) fn recognize_statement_effect(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    if fcx.scope().temporal_rewrite_can_apply(expr) {
        return None;
    }
    statement_position::has_runtime_expr(expr).then(|| {
        Box::new(StatementRuntimeExprSugar {
            boundary: token_key(expr),
        }) as Box<dyn Sugar>
    })
}

pub(crate) fn recognize_constraint(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    if fcx.scope().temporal_rewrite_can_apply(expr) {
        return None;
    }
    statement_position::is_runtime_mutation_statement(expr).then(|| {
        Box::new(StatementRuntimeExprSugar {
            boundary: token_key(expr),
        }) as Box<dyn Sugar>
    })
}

struct StatementRuntimeExprSugar {
    boundary: String,
}

impl Sugar for StatementRuntimeExprSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::RuntimeExprStmt {
            boundary: self.boundary.clone(),
        })
    }
}
