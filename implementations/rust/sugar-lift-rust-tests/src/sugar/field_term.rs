// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Field` (`base.member`): the base child is constructed
// by the factory, and desugar visits the floor it returns. Tuple-component floors
// project directly; ordinary term floors emit the congruent `field:<member>` ctor.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::sugar::factory::{
    has_tuple_producer, SugarBody, SugarBuildCtx, TermFloor, TupleProducerFloor,
};
use crate::sugar::term_dispatch::{DesugaredFloorAccept, DesugaredFloorVisitor};
use crate::{token_key, Desugared, Outcome, Sugar, SugarCtx};
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("field_term", recognize);

/// TERM recognizer for `Expr::Field`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Field(field)
            if matches!(field.member, syn::Member::Unnamed(_))
                && has_tuple_producer(&field.base, fcx) =>
        {
            Some(Box::new(FieldTermSugar {
                member: token_key(&field.member),
                base: FieldBase::Tuple {
                    body: SugarBody::tuple_producer(&field.base, fcx),
                },
                tuple_index: tuple_index(&field.member),
            }))
        }
        Expr::Field(field) => Some(Box::new(FieldTermSugar {
            member: token_key(&field.member),
            base: FieldBase::Term {
                body: SugarBody::term(&field.base, fcx),
            },
            tuple_index: tuple_index(&field.member),
        })),
        _ => None,
    }
}

struct FieldTermSugar {
    member: String,
    base: FieldBase,
    tuple_index: Option<usize>,
}

enum FieldBase {
    Term { body: SugarBody<TermFloor> },
    Tuple { body: SugarBody<TupleProducerFloor> },
}

impl Sugar for FieldTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let floor = match &self.base {
            FieldBase::Term { body } => match body.reduce(ctx) {
                Outcome::Complete(floor) => floor,
                Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
            },
            FieldBase::Tuple { body } => match body.reduce(ctx) {
                Outcome::Complete(floor) => floor,
                Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
            },
        };
        floor.accept_desugared_floor(FieldProjectionVisitor {
            member: &self.member,
            tuple_index: self.tuple_index,
        })
    }
}

struct FieldProjectionVisitor<'a> {
    member: &'a str,
    tuple_index: Option<usize>,
}

impl DesugaredFloorVisitor for FieldProjectionVisitor<'_> {
    type Output = Outcome;

    fn visit_term(self, term: Rc<Term>) -> Self::Output {
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: format!("field:{}", self.member),
            args: vec![term],
        })))
    }

    fn visit_term_seq(self, _terms: Vec<Rc<Term>>) -> Self::Output {
        field_gap(self.member)
    }

    fn visit_tuple_components(self, parts: Vec<Rc<Term>>) -> Self::Output {
        let index = self.tuple_index.unwrap_or_else(|| field_gap(self.member));
        let term = parts
            .get(index)
            .cloned()
            .unwrap_or_else(|| field_gap(self.member));
        Outcome::Complete(Desugared::Term(term))
    }

    fn visit_passthrough(self, _floor: Desugared) -> Self::Output {
        field_gap(self.member)
    }
}

fn tuple_index(member: &syn::Member) -> Option<usize> {
    match member {
        syn::Member::Unnamed(index) => Some(index.index as usize),
        syn::Member::Named(_) => None,
    }
}

fn field_gap(member: &str) -> ! {
    panic!(
        "FieldTermSugar `{member}` base completed a floor that cannot own field projection; write more Sugar for this AST"
    )
}
