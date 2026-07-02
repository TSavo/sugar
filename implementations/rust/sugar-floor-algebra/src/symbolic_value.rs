// SPDX-License-Identifier: Apache-2.0

use std::rc::Rc;

use sugar_ir_symbolic::Term;

#[derive(Clone)]
pub struct SymbolicValue {
    term: Rc<Term>,
}

impl SymbolicValue {
    pub fn from_term(term: Rc<Term>) -> Option<Self> {
        match term.as_ref() {
            Term::Var { .. } => Some(Self { term }),
            _ => None,
        }
    }

    pub fn term(&self) -> &Rc<Term> {
        &self.term
    }
}
