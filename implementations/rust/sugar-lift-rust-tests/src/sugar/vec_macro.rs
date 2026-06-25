// SPDX-License-Identifier: Apache-2.0
//
// `VecMacroSugar`: compiler/std macro sugar for literal `vec![a, b, ...]`.
// The repeat form `vec![x; n]` is deliberately not claimed here; array-repeat
// style cardinality is a separate sugar shape.

use syn::Expr;
use tracing::debug;

use crate::sugar::aggregate_term::LiteralAggregateTermSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx};
use crate::{parse_macro_args, Sugar};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("vec_macro", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(expr_macro) = expr else {
        return None;
    };
    if !expr_macro
        .mac
        .path
        .segments
        .last()
        .is_some_and(|seg| seg.ident == "vec")
    {
        return None;
    }
    let args = parse_macro_args(expr_macro.mac.tokens.clone()).ok()?;
    debug!(
        target: "sugar_lift_rust_tests::sugar::vec_macro",
        len = args.exprs.len(),
        "recognized literal vec macro"
    );
    Some(Box::new(LiteralAggregateTermSugar::new(
        "Vec",
        args.exprs
            .iter()
            .map(|elem| SugarBody::term(elem, fcx))
            .collect(),
    )))
}
