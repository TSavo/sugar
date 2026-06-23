// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Range` (`a..b` / `a..=b`): `range`/`range_incl` over
// start (or `0`) and end (or `range_end_len`). Byte-identical to the `Expr::Range` arm
// of the old fat factory.

use sugar_ir_symbolic::{make_var, num};

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx};
use crate::sugar::term_leaf::resolved_term;
use crate::Sugar;
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("range_term", recognize);

/// TERM recognizer for `Expr::Range`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Range(range) = expr else {
        return None;
    };
    let name = match range.limits {
        syn::RangeLimits::HalfOpen(_) => "range",
        syn::RangeLimits::Closed(_) => "range_incl",
    };
    let start = match range.start.as_deref() {
        Some(expr) => SugarBody::term(expr, fcx),
        None => SugarBody::from_node(resolved_term(num(0))),
    };
    let end = match range.end.as_deref() {
        Some(expr) => SugarBody::term(expr, fcx),
        None => SugarBody::from_node(resolved_term(make_var("range_end_len"))),
    };
    Some(Box::new(CtorSugar::new(name, vec![start, end])))
}
