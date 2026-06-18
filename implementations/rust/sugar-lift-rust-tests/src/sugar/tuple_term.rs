// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Tuple`: the `literal_aggregate_term` "Tuple" ctor over
// the element exprs. Byte-identical to the `Expr::Tuple` arm of the old fat factory.

use crate::sugar::factory::FactoryCtx;
use crate::sugar::term_leaf::{reasoned_hit, resolved_term};
use crate::{literal_aggregate_term_in_scope, Sugar};
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("tuple_term", recognize);

/// TERM recognizer for `Expr::Tuple`: the `literal_aggregate_term("Tuple", ..)` arm.
pub(crate) fn recognize(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Tuple(tuple) = expr else {
        return None;
    };
    match literal_aggregate_term_in_scope("Tuple", tuple.elems.iter(), expr, fcx.scope) {
        Ok(term) => Some(resolved_term(term)),
        Err(reason) => Some(reasoned_hit(reason)),
    }
}
