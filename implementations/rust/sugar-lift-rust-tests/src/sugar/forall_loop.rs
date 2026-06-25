// SPDX-License-Identifier: Apache-2.0
//
// `for <var> in <literal-domain>` bounded universal sugar.

use std::collections::BTreeMap;

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::forall;
use crate::sugar::statement_position;
use crate::{
    FactoryAuditLog, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar, TemporalScope,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("forall_loop", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::ForLoop(f) => forall::decompose_for_loop(f, fcx.scope(), fcx.let_inits(), fcx)
            .map(|node| Box::new(node) as Box<dyn Sugar>),
        _ => None,
    }
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn desugar_statement_for_loop(
    expr: &Expr,
    scope: &TemporalScope,
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    float_widths: &mut FloatWidthScope,
    let_inits: &BTreeMap<String, &Expr>,
    macro_depth: usize,
    factory_audits: Option<&FactoryAuditLog>,
) -> Outcome {
    statement_position::desugar_composite_expr(
        expr,
        scope,
        options,
        reducer,
        float_widths,
        let_inits,
        macro_depth,
        factory_audits,
    )
}
