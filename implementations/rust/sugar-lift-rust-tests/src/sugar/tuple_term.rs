// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Tuple`: the `literal_aggregate_term` "Tuple" ctor over
// the element exprs. The same source shape also owns a tuple-component floor so
// field projection and tuple equality can visit components instead of reverse-
// parsing the `literal:Tuple(...)` term key.

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::term_leaf::{reasoned_incomplete, resolved_term};
use crate::{literal_aggregate_term_in_scope, Desugared, Outcome, Sugar, SugarCtx};
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("tuple_term", recognize);

pub(crate) const TUPLE_PRODUCER_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::tuple_producer(
        "literal_tuple_producer",
        recognize_tuple_producer,
    );

/// TERM recognizer for `Expr::Tuple`: the `literal_aggregate_term("Tuple", ..)` arm.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Tuple(tuple) = expr else {
        return None;
    };
    match literal_aggregate_term_in_scope("Tuple", tuple.elems.iter(), expr, fcx.scope()) {
        Ok(term) => Some(resolved_term(term)),
        Err(reason) => Some(reasoned_incomplete(reason)),
    }
}

fn recognize_tuple_producer(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Tuple(tuple) = expr else {
        return None;
    };
    Some(Box::new(LiteralTupleProducer {
        elems: tuple
            .elems
            .iter()
            .map(|elem| SugarBody::term(elem, fcx))
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
