// SPDX-License-Identifier: Apache-2.0
//
// IrTerm boundary-collapse campaign (#3192), Slice 2.
//
// This module is the single sanctioned crossing between `sugar-walk`'s wire
// `IrTerm` representation and the floor algebra's `Rc<Term>` representation.
// It deliberately delegates to `sugar-ir-symbolic::convert`; any hand-rolled
// structural conversion belongs in that crate, not here.

use std::rc::Rc;

use sugar_ir_symbolic::convert::{formula_from_ir, formula_to_ir, term_from_ir, term_to_ir};
use sugar_ir_symbolic::{Formula, Term};
use sugar_ir_types::{Formula as IrFormula, Term as IrTerm};

pub fn lower_ir(term: &IrTerm) -> Rc<Term> {
    Rc::new(term_from_ir(term.clone()))
}

pub fn raise_ir(term: &Rc<Term>) -> IrTerm {
    term_to_ir(term)
}

pub fn lower_ir_formula(formula: &IrFormula) -> Rc<Formula> {
    Rc::new(formula_from_ir(formula.clone()))
}

pub fn raise_ir_formula(formula: &Rc<Formula>) -> IrFormula {
    formula_to_ir(formula)
}

pub fn pattern_tuple_projection(receiver: &IrTerm, index: usize) -> IrTerm {
    raise_ir(&sugar_floor_algebra::tuple_projection(
        lower_ir(receiver),
        index,
    ))
}

pub fn pattern_tuple_struct_projection(receiver: &IrTerm, index: usize) -> IrTerm {
    raise_ir(&sugar_floor_algebra::tuple_struct_projection(
        lower_ir(receiver),
        index,
    ))
}

pub fn pattern_field_projection(receiver: &IrTerm, field_name: &str) -> IrTerm {
    raise_ir(&sugar_floor_algebra::field_projection(
        lower_ir(receiver),
        field_name,
    ))
}

pub fn pattern_index_projection(receiver: &IrTerm, index: usize) -> IrTerm {
    raise_ir(&sugar_floor_algebra::index_projection(
        lower_ir(receiver),
        index,
    ))
}
