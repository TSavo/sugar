// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for the TRANSPARENT wrappers `Expr::Paren` (`(expr)`) and
// `Expr::Group` (an invisible group): recurse straight through to the inner expr's
// term Sugar. Byte-identical to the `Expr::Paren`/`Expr::Group` arms of the old fat
// factory.

use crate::sugar::factory::{build_composite, build_term, SugarBuildCtx};
use crate::Sugar;
use syn::Expr;
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const TERM_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("transparent_term", recognize);

pub(crate) const COMPOSITE_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("transparent_composite", recognize_composite);

/// TERM recognizer for `Expr::Paren` / `Expr::Group`: recurse through to the inner
/// expr's TERM Sugar.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    match expr {
        Expr::Paren(paren) => Some(build_term(&paren.expr, fcx)),
        Expr::Group(group) => Some(build_term(&group.expr, fcx)),
        _ => None,
    }
}

/// COMPOSITE recognizer for `Expr::Paren` / `Expr::Group`: recurse through to the inner
/// expr's COMPOSITE Sugar. Byte-identical to the `Expr::Paren`/`Expr::Group` arms of the
/// old fat `build_composite`.
pub(crate) fn recognize_composite(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    match expr {
        Expr::Paren(p) => Some(build_composite(&p.expr, fcx)),
        Expr::Group(g) => Some(build_composite(&g.expr, fcx)),
        _ => None,
    }
}
