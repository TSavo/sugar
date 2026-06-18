// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Array` in TERM position: the `literal_aggregate_term`
// "Array" ctor over the element exprs. This is the TERM-position node — DISTINCT from
// the sequence-floor `LiteralSugar` (`literal.rs`) the COMPOSITE catalog routes
// `Expr::Array` to. The two roles genuinely differ (a term aggregate vs a `Seq`
// domain), so they are SEPARATE nodes per role — never one node on a position
// flag. Byte-identical to the `Expr::Array` arm of the old fat factory.

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::term_leaf::{reasoned_hit, resolved_term};
use crate::{literal_aggregate_term_in_scope, Sugar};
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("array_term", recognize);

/// TERM recognizer for `Expr::Array`: the `literal_aggregate_term("Array", ..)` arm.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Array(array) = expr else {
        return None;
    };
    match literal_aggregate_term_in_scope("Array", array.elems.iter(), expr, fcx.scope()) {
        Ok(term) => Some(resolved_term(term)),
        Err(reason) => Some(reasoned_hit(reason)),
    }
}
