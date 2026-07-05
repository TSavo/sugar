// SPDX-License-Identifier: MIT OR Apache-2.0

use std::rc::Rc;

use sugar_ir_symbolic::Formula;

#[derive(Clone)]
pub struct PredicateValue {
    formula: Rc<Formula>,
}

impl PredicateValue {
    pub fn new(formula: Rc<Formula>) -> Self {
        Self { formula }
    }

    pub fn formula(&self) -> &Rc<Formula> {
        &self.formula
    }

    pub fn into_formula(self) -> Rc<Formula> {
        self.formula
    }
}
