// SPDX-License-Identifier: Apache-2.0
//
// PredicateValue floor.
//
// Python reference: `floor/predicate_value.py` carries a `Formula` while
// `floor/bool_value.py` carries a literal data bool that may project to a term.
// Rust has no dynamic FloorValue class hierarchy, so the distinction is an
// explicit `Desugared` variant plus closed visitor dispatch.

use std::rc::Rc;

use sugar_ir_symbolic::Formula;

#[derive(Clone)]
pub(crate) struct PredicateValue {
    formula: Rc<Formula>,
}

impl PredicateValue {
    pub(crate) fn new(formula: Rc<Formula>) -> Self {
        Self { formula }
    }

    pub(crate) fn formula(&self) -> &Rc<Formula> {
        &self.formula
    }

    pub(crate) fn into_formula(self) -> Rc<Formula> {
        self.formula
    }
}
