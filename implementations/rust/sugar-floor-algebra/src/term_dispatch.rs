// SPDX-License-Identifier: Apache-2.0

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::{desugared_floor_name, Desugared, PredicateValue, SymbolicValue};

pub trait TermFloorVisitor {
    type Output;

    fn visit_term(self, term: &Rc<Term>) -> Self::Output;
}

pub trait TermFloorAccept {
    fn accept_term_floor<V: TermFloorVisitor>(&self, visitor: V) -> V::Output;
}

impl TermFloorAccept for Rc<Term> {
    fn accept_term_floor<V: TermFloorVisitor>(&self, visitor: V) -> V::Output {
        visitor.visit_term(self)
    }
}

pub trait SymbolicValueFloorVisitor {
    type Output;

    fn visit_symbolic_value(self, value: SymbolicValue) -> Self::Output;
    fn visit_non_symbolic(self, term: &Rc<Term>) -> Self::Output;
}

pub trait SymbolicValueFloorAccept {
    fn accept_symbolic_value_floor<V: SymbolicValueFloorVisitor>(&self, visitor: V) -> V::Output;
}

impl SymbolicValueFloorAccept for Rc<Term> {
    fn accept_symbolic_value_floor<V: SymbolicValueFloorVisitor>(&self, visitor: V) -> V::Output {
        match SymbolicValue::from_term(Rc::clone(self)) {
            Some(value) => visitor.visit_symbolic_value(value),
            None => visitor.visit_non_symbolic(self),
        }
    }
}

pub trait PredicateValueFloorVisitor {
    type Output;

    fn visit_predicate_value(self, value: PredicateValue) -> Self::Output;
    fn visit_non_predicate(self, floor: Desugared) -> Self::Output;
}

pub trait PredicateValueFloorAccept {
    fn accept_predicate_value_floor<V: PredicateValueFloorVisitor>(self, visitor: V) -> V::Output;
}

impl PredicateValueFloorAccept for Desugared {
    fn accept_predicate_value_floor<V: PredicateValueFloorVisitor>(self, visitor: V) -> V::Output {
        match self {
            Desugared::PredicateValue(value) => visitor.visit_predicate_value(value),
            floor => visitor.visit_non_predicate(floor),
        }
    }
}

pub struct RequiredPredicateValueVisitor<'a> {
    pub owner: &'a str,
}

impl PredicateValueFloorVisitor for RequiredPredicateValueVisitor<'_> {
    type Output = PredicateValue;

    fn visit_predicate_value(self, value: PredicateValue) -> Self::Output {
        value
    }

    fn visit_non_predicate(self, floor: Desugared) -> Self::Output {
        panic!(
            "{} completed {} floor where a PredicateValue floor was required",
            self.owner,
            desugared_floor_name(&floor)
        )
    }
}
