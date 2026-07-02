// SPDX-License-Identifier: Apache-2.0

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::SymbolicValue;

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
