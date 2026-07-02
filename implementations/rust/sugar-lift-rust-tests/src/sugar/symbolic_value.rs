// SPDX-License-Identifier: Apache-2.0

//! SymbolicValue floor.
//!
//! Python reference: `floor/symbolic_value.py` carries a ProofIR term while
//! committing to no carrier sort; the backend chooses the sort from surrounding
//! operations. This item exposes the closed floor over `Term::Var` names.
//! Composed symbolic terms stay on the existing Term floor until a later
//! operation floor needs to split them out.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

/// A sort-neutral symbolic value.
#[derive(Clone)]
pub(crate) struct SymbolicValue {
    term: Rc<Term>,
}

impl SymbolicValue {
    pub(crate) fn from_term(term: Rc<Term>) -> Option<Self> {
        match term.as_ref() {
            Term::Var { .. } => Some(Self { term }),
            _ => None,
        }
    }

    #[allow(dead_code)]
    pub(crate) fn term(&self) -> &Rc<Term> {
        &self.term
    }
}
