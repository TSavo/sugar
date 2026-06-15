// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for the TRANSPARENT wrappers `Expr::Paren` (`(expr)`) and
// `Expr::Group` (an invisible group): recurse straight through to the inner expr's
// term Sugar. Byte-identical to the `Expr::Paren`/`Expr::Group` arms of the old fat
// factory.

use crate::sugar::factory::{build_composite, build_term, FactoryCtx};
use crate::Sugar;
use syn::Expr;

/// TERM recognizer for `Expr::Paren` / `Expr::Group`: recurse through to the inner
/// expr's TERM Sugar.
pub(crate) fn recognize(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Paren(paren) => Some(build_term(&paren.expr, fcx)),
        Expr::Group(group) => Some(build_term(&group.expr, fcx)),
        _ => None,
    }
}

/// COMPOSITE recognizer for `Expr::Paren` / `Expr::Group`: recurse through to the inner
/// expr's COMPOSITE Sugar. Byte-identical to the `Expr::Paren`/`Expr::Group` arms of the
/// old fat `build_composite`.
pub(crate) fn recognize_composite(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Paren(p) => Some(build_composite(&p.expr, fcx)),
        Expr::Group(g) => Some(build_composite(&g.expr, fcx)),
        _ => None,
    }
}
