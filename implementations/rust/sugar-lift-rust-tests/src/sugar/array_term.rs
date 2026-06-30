// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Array` in TERM position: the `literal_aggregate_term`
// "Array" ctor over the element exprs. This is the TERM-position node — DISTINCT from
// the sequence-floor `LiteralSugar` (`literal.rs`) the COMPOSITE catalog routes
// `Expr::Array` to. The two roles genuinely differ (a term aggregate vs a `Seq`
// domain), so they are SEPARATE nodes per role — never one node on a position
// flag. Byte-identical to the `Expr::Array` arm of the old fat factory.

use crate::sugar::aggregate_term::LiteralAggregateTermSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx};
use crate::Sugar;
use syn::Expr;
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("array_term", recognize);

/// TERM recognizer for `Expr::Array`: the `literal_aggregate_term("Array", ..)` arm.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Array(array) = expr else {
        return None;
    };
    Some(Box::new(LiteralAggregateTermSugar::new(
        "Array",
        array
            .elems
            .iter()
            .map(|elem| SugarBody::term(elem, fcx))
            .collect(),
    )))
}
