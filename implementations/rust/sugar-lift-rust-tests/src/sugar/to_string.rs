// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for closed stdlib `<literal>.to_string()`. Unknown receivers
// decline so generic MethodSugar can continue digging the method-call universe.

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::format::{build_literal_string_term_node, is_to_string_shape};
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "to_string",
        &["method", "transparent_term"],
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if !is_to_string_shape(expr) {
        return None;
    }
    Some(build_literal_string_term_node(expr, fcx))
}
