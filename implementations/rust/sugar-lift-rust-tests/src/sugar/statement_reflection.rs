// SPDX-License-Identifier: Apache-2.0
//
// Statement-position compile-time-reflection sugar.

use syn::Expr;

use crate::sugar::claim::{SugarPriority, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::statement_position;
use crate::{Effect, Outcome, Sugar, SugarCtx, STRUCTURAL_BACKSTOP_REASON};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::new(
        "statement_reflection",
        SugarRole::StatementEffect,
        SugarPriority::Secondary,
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    statement_position::reflection_boundary(expr)
        .map(|_| Box::new(StatementReflectionSugar { expr: expr.clone() }) as Box<dyn Sugar>)
}

struct StatementReflectionSugar {
    expr: Expr,
}

impl Sugar for StatementReflectionSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        if let Some(boundary) = statement_position::reflection_boundary(&self.expr) {
            return Outcome::Hit(Effect::Reflection { boundary });
        }
        Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })
    }
}
