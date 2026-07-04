// SPDX-License-Identifier: MIT OR Apache-2.0
//
// TERM recognizer for `Expr::Await` (`base.await`): the `await` ctor over the already
// constructed base child. The parent node is born with its body Sugar; desugar never
// goes back to the factory through a raw child expression.

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "await_term",
        crate::sugar::claim::SugarWitnesses::reasoned_bucket(
            "async await runtime handoff; verdict pair needs executor/future witness machinery",
        ),
        recognize,
    );

/// TERM recognizer for `Expr::Await`.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let base_frag = frag.await_base()?;
    Some(Box::new(CtorSugar::new(
        "await",
        vec![SugarBody::term_frag(&base_frag, fcx)],
    )))
}

#[cfg(test)]
mod tests {
    use crate::sugar::source_fragment::{FragNode, SourceFragment};
    use syn::Expr;

    fn e(src: &str) -> Expr {
        syn::parse_str(src).expect("parse expr")
    }

    #[test]
    fn from_src_await_base_is_some() {
        // positive: `fut.await` -> await_base() returns Some fragment
        // Expr::Await is observed as "Other:Expr:Await" (not explicitly mapped in expr_kind)
        let expr = e("fut.await");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        assert_eq!(
            frag.observed(),
            "Other:Expr:Await",
            "Await falls to Other bucket"
        );
        assert!(
            frag.await_base().is_some(),
            "await_base() must be Some for an Await fragment"
        );
    }

    #[test]
    fn discrimination_non_await_returns_none_from_await_base() {
        // discrimination: a BinOp fragment returns None from await_base
        let expr = e("1 + 2");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        assert!(
            frag.await_base().is_none(),
            "BinOp should not have await_base"
        );
    }

    #[test]
    fn structural_await_base_observed_is_name() {
        // structural: the base of `fut.await` is a path (Expr::Path -> "Name")
        let expr = e("fut.await");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        let base = frag.await_base().expect("await base must be present");
        // Expr::Path is observed as "Name" in expr_kind
        assert_eq!(
            base.observed(),
            "Name",
            "base of `fut.await` should be a Name (Expr::Path)"
        );
    }
}
