// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for closed stdlib `concat!(...)`. The concatenation semantics
// live here, ahead of the generic macro fallback.

use syn::Expr;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::format::{build_literal_string_term_node, is_concat_macro_shape};
use crate::Sugar;
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "concat_macro",
        &["macro_term", "reference_term"],
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    if !is_concat_macro_shape(expr) {
        return None;
    }
    Some(build_literal_string_term_node(expr, fcx))
}
