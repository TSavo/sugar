// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for the TRANSPARENT wrappers `Expr::Paren` (`(expr)`) and
// `Expr::Group` (an invisible group): recurse straight through to the inner expr's
// term Sugar. Byte-identical to the `Expr::Paren`/`Expr::Group` arms of the old fat
// factory.

use crate::sugar::factory::{build_composite_frag, build_term_frag, SugarBuildCtx};
use crate::Sugar;
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const TERM_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("transparent_term", recognize);

pub(crate) const COMPOSITE_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("transparent_composite", recognize_composite);

/// TERM recognizer for `Expr::Paren` / `Expr::Group`: recurse through to the inner
/// expr's TERM Sugar.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let inner = frag.transparent_inner()?;
    Some(build_term_frag(&inner, fcx))
}

/// COMPOSITE recognizer for `Expr::Paren` / `Expr::Group`: recurse through to the inner
/// expr's COMPOSITE Sugar. Byte-identical to the `Expr::Paren`/`Expr::Group` arms of the
/// old fat `build_composite`.
pub(crate) fn recognize_composite(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let inner = frag.transparent_inner()?;
    Some(build_composite_frag(&inner, fcx))
}

#[cfg(test)]
mod tests {
    use crate::sugar::source_fragment::{FragNode, SourceFragment};
    use syn::Expr;

    fn e(src: &str) -> Expr {
        syn::parse_str(src).expect("parse expr")
    }

    #[test]
    fn from_src_paren_transparent_inner_is_some() {
        // positive: (42) -- Paren fragment transparent_inner returns Some inner lit
        let expr = e("(42)");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        assert_eq!(frag.observed(), "Paren", "observed must be Paren");
        let inner = frag.transparent_inner()
            .expect("transparent_inner must be Some for Paren");
        assert_eq!(
            inner.observed(), "PrimitiveLiteral",
            "inner of (42) should be PrimitiveLiteral"
        );
    }

    #[test]
    fn discrimination_binop_returns_none_from_transparent_inner() {
        // discrimination: a BinOp is not transparent
        let expr = e("1 + 2");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        assert!(
            frag.transparent_inner().is_none(),
            "BinOp must not have transparent_inner"
        );
    }

    #[test]
    fn structural_paren_inner_observed_is_primitive_literal() {
        // structural: `(99)` -> Paren -> inner is PrimitiveLiteral
        let expr = e("(99)");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        assert_eq!(frag.observed(), "Paren");
        let inner = frag.transparent_inner().unwrap();
        assert_eq!(inner.observed(), "PrimitiveLiteral");
    }
}
