// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Tuple`: the `literal_aggregate_term` "Tuple" ctor over
// the element exprs. The same source shape also owns a tuple-component floor so
// field projection and tuple equality can visit components instead of reverse-
// parsing the `literal:Tuple(...)` term key.

use crate::sugar::aggregate_term::LiteralAggregateTermSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "tuple_term",
        crate::sugar::claim::SugarWitnesses::Pending,
        recognize,
    );

pub(crate) const TUPLE_PRODUCER_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::tuple_producer(
        "literal_tuple_producer",
        crate::sugar::claim::SugarWitnesses::Pending,
        recognize_tuple_producer,
    );

/// TERM recognizer for `Expr::Tuple`: the `literal_aggregate_term("Tuple", ..)` arm.
/// No `as_expr()`, `Expr::`, or raw syn in this function.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let elems = frag.tuple_elems()?;
    Some(Box::new(LiteralAggregateTermSugar::new(
        "Tuple",
        elems
            .iter()
            .map(|ef| SugarBody::term_frag(ef, fcx))
            .collect(),
    )))
}

fn recognize_tuple_producer(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let elems = frag.tuple_elems()?;
    Some(Box::new(LiteralTupleProducer {
        elems: elems
            .iter()
            .map(|ef| SugarBody::term_frag(ef, fcx))
            .collect(),
    }))
}

struct LiteralTupleProducer {
    elems: Vec<SugarBody<TermFloor>>,
}

impl Sugar for LiteralTupleProducer {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let mut parts = Vec::with_capacity(self.elems.len());
        for elem in &self.elems {
            let term = match elem.reduce(ctx) {
                Outcome::Complete(desugared) => desugared
                    .into_term()
                    .unwrap_or_else(|| panic!("literal tuple element reduced to non-term")),
                Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
            };
            parts.push(term);
        }
        Outcome::Complete(Desugared::TupleComponents(parts))
    }
}

// ---------------------------------------------------------------------------
// Phase-3 from_src tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use crate::{LiftOptions, TemporalPlan, TemporalScope};
    use std::collections::BTreeMap;
    use syn::Expr;

    /// Positive: `(1_i32, 2_i32)` is a Tuple with 2 elements; recognize returns Some.
    #[test]
    fn from_src_tuple_two_elems_recognized() {
        let expr: Expr = syn::parse_str("(1_i32, 2_i32)").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert_eq!(frag.observed(), "Tuple");
        let elems = frag.tuple_elems().expect("tuple_elems must return Some");
        assert_eq!(elems.len(), 2);

        let scope = TemporalScope::new("tuple-term-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(recognize(&frag, &fcx).is_some(), "(1,2) must be recognized");
    }

    /// Discrimination: an array is not a tuple.
    #[test]
    fn from_src_array_not_recognized_as_tuple() {
        let expr: Expr = syn::parse_str("[1_i32, 2_i32]").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert_eq!(frag.observed(), "Array");
        assert!(
            frag.tuple_elems().is_none(),
            "array must not have tuple_elems"
        );

        let scope = TemporalScope::new("tuple-term-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_none(),
            "array must not be recognized as Tuple"
        );
    }

    /// Structural: empty tuple `()` has 0 elements and is recognized.
    #[test]
    fn from_src_unit_tuple_zero_elems() {
        let expr: Expr = syn::parse_str("()").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert_eq!(frag.observed(), "Tuple");
        let elems = frag
            .tuple_elems()
            .expect("unit tuple must have tuple_elems");
        assert_eq!(elems.len(), 0, "unit tuple has 0 elements");

        let scope = TemporalScope::new("tuple-term-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        assert!(
            recognize(&frag, &fcx).is_some(),
            "() must be recognized as Tuple"
        );
    }
}
