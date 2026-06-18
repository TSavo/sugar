// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Range` (`a..b` / `a..=b`): `range`/`range_incl` over
// start (or `0`) and end (or `range_end_len`). Byte-identical to the `Expr::Range` arm
// of the old fat factory.

use sugar_ir_symbolic::{make_var, num};

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{build_term, SugarBuildCtx};
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
    let start: Box<dyn Sugar> = match &range.start {
        Some(expr) => build_term(expr, fcx),
        None => resolved_term(num(0)),
    };
    let end: Box<dyn Sugar> = match &range.end {
        Some(expr) => build_term(expr, fcx),
        None => resolved_term(make_var("range_end_len")),
    };
    let name = match range.limits {
        syn::RangeLimits::HalfOpen(_) => "range",
        syn::RangeLimits::Closed(_) => "range_incl",
    };
    Some(Box::new(CtorSugar::new(name, vec![start, end])))
}
