// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for closed string `+`. Numeric and otherwise unresolved `+`
// expressions decline to the generic BinOpSugar fallback.

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::format::{build_literal_string_term_node, is_factory_string_add_shape};
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before("string_add", &["binop"], recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if !is_factory_string_add_shape(expr, fcx) {
        return None;
    }
    Some(build_literal_string_term_node(expr, fcx))
}
