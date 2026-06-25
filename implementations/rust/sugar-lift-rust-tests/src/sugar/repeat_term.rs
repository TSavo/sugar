// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Repeat` (`[elem; N]`) in TERM position: a literal or
// scope-resolved const count expands to the N-fold `literal_aggregate_term` "Array";
// a runtime/opaque count is the `ArrayRepeatSugar` refuse-shape (`Effect::ArrayRepeat`).
// This is the TERM-position
// node — DISTINCT from the COMPOSITE-catalog `Expr::Repeat` (which boxes
// `decompose_array_repeat` directly as the refuse-shape). Byte-identical to the
// `Expr::Repeat` arm of the old fat factory.

use crate::sugar::aggregate_term::LiteralAggregateTermSugar;
use crate::sugar::array_repeat;
use crate::sugar::factory::{SugarBody, SugarBuildCtx};
use crate::{repeat_count_in_scope, Sugar};
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("repeat_term", recognize);

/// TERM recognizer for `Expr::Repeat`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Repeat(repeat) = expr else {
        return None;
    };
    let scope = fcx.scope();
    let Some(count) = repeat_count_in_scope(&repeat.len, scope) else {
        return Some(array_repeat::refusal_node(expr));
    };
    const MAX_REPEAT: usize = 4096;
    if count > MAX_REPEAT {
        return Some(array_repeat::refusal_node(expr));
    }
    Some(Box::new(LiteralAggregateTermSugar::new(
        "Array",
        std::iter::repeat_with(|| SugarBody::term(&repeat.expr, fcx))
            .take(count)
            .collect(),
    )))
}
