// SPDX-License-Identifier: Apache-2.0
//
// `WrappingNegSugar`: primitive integer `.wrapping_neg()` over a grounded literal is
// a stdlib/compiler axiom. The receiver child owns the numeric floor; this sugar only
// asks that floor to perform the typed wrapping operation and reifies the result.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{numeric_floor_from_term, WrappingNegVisitor};
use crate::sugar::primitive_int::deferred_primitive_method_term;
use crate::sugar::source_fragment::SourceFragment;
use crate::{term_contains_curry_param, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "wrapping_neg",
    SugarRole::Term,
    crate::sugar::claim::SugarWitnesses::Pending,
    recognize,
);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let stripped = frag.strip_refs_groups();
    if stripped.call_method_key().as_deref() != Some("wrapping_neg") {
        return None;
    }
    if stripped.call_arg_count() != 0 {
        return None;
    }
    let receiver_frag = stripped.call_receiver()?;
    Some(Box::new(WrappingNegSugar {
        receiver: SugarBody::term_frag(&receiver_frag, fcx),
    }))
}

struct WrappingNegSugar {
    receiver: SugarBody<TermFloor>,
}

impl Sugar for WrappingNegSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match term_body(&self.receiver, ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        if term_contains_curry_param(&receiver) {
            return Outcome::Complete(Desugared::Term(deferred_primitive_method_term(
                "wrapping_neg",
                receiver,
                Vec::new(),
            )));
        }
        let Some(floor) = numeric_floor_from_term(&receiver) else {
            panic!(
                "wrapping_neg receiver did not reduce to a numeric floor; write the owning Sugar before Outcome"
            );
        };
        let Some(result) = floor.accept(WrappingNegVisitor) else {
            panic!(
                "wrapping_neg numeric floor could not compute a result; write the owning typed floor before Outcome"
            );
        };
        let Some(term) = result.term() else {
            panic!("wrapping_neg numeric floor could not reify its result term");
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::wrapping_neg",
            ?floor,
            ?result,
            "resolved primitive wrapping_neg stdlib axiom to literal"
        );
        Outcome::Complete(Desugared::Term(term))
    }
}

fn term_body(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| panic!("term body completed as non-term before wrapping_neg"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

#[cfg(test)]
mod tests {
    use crate::sugar::source_fragment::{FragNode, SourceFragment};
    use syn::Expr;

    fn e(src: &str) -> Expr {
        syn::parse_str(src).expect("parse expr")
    }

    #[test]
    fn from_src_wrapping_neg_method_key_is_wrapping_neg() {
        // positive: x.wrapping_neg() -> call_method_key == "wrapping_neg", 0 args
        let expr = e("x.wrapping_neg()");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        assert_eq!(frag.observed(), "MethodCall", "observed must be MethodCall");
        assert_eq!(
            frag.call_method_key().as_deref(),
            Some("wrapping_neg"),
            "method key must be wrapping_neg"
        );
        assert_eq!(frag.call_arg_count(), 0, "wrapping_neg takes no args");
        assert!(frag.call_receiver().is_some(), "receiver must be present");
    }

    #[test]
    fn discrimination_wrapping_add_not_accepted() {
        // discrimination: wrapping_add has a different method key
        let expr = e("x.wrapping_add(y)");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        assert_ne!(
            frag.call_method_key().as_deref(),
            Some("wrapping_neg"),
            "wrapping_add must not match wrapping_neg key"
        );
    }

    #[test]
    fn structural_wrapping_neg_receiver_observed_is_name() {
        // structural: the receiver of `x.wrapping_neg()` is Expr::Path -> observed "Name"
        let expr = e("x.wrapping_neg()");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        let receiver = frag.call_receiver().expect("receiver must be present");
        // Expr::Path maps to "Name" in expr_kind()
        assert_eq!(
            receiver.observed(),
            "Name",
            "receiver of x.wrapping_neg() is Expr::Path -> 'Name'"
        );
    }
}
