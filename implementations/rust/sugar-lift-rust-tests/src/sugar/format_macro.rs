// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for closed stdlib `format!(...)`. This is the specific
// format-surface owner; generic macro recursion only handles unresolved cases.

use sugar_ir_symbolic::str_const;
use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::format::{is_format_macro_shape, stable_let_bindings, try_resolve_format};
use crate::sugar::term_leaf::{reasoned_hit, resolved_term};
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("format_macro", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if !is_format_macro_shape(expr) {
        return None;
    }
    let stable = stable_let_bindings(fcx.scope());
    match try_resolve_format(expr, &stable) {
        Ok(Some(s)) => Some(resolved_term(str_const(s))),
        Err(reason) => Some(reasoned_hit(reason)),
        Ok(None) => None,
    }
}
