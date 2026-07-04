// SPDX-License-Identifier: MIT OR Apache-2.0
//
// IrTerm boundary-collapse campaign (#3192), Slice 2.
//
// This module is the single sanctioned crossing between `sugar-walk`'s wire
// `IrTerm` representation and the floor algebra's `Rc<Term>` representation.
// It deliberately delegates to `sugar-ir-symbolic::convert`; any hand-rolled
// structural conversion belongs in that crate, not here.

use std::rc::Rc;

use sugar_floor_algebra::GuardedReturn;
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

pub fn raise_guarded_return_ir(guarded_return: GuardedReturn) -> IrTerm {
    let (guards, term) = guarded_return.into_parts();
    guards
        .into_iter()
        .rev()
        .fold(raise_ir(&term), |value, guard| {
            let guard =
                formula_to_legacy_guard_term(raise_ir_formula(&guard)).unwrap_or_else(|| {
                    panic!("ControlFlowGuardOperation produced non-term branch guard")
                });
            IrTerm::Ctor {
                name: "cf_guarded".to_string(),
                args: vec![guard, value],
            }
        })
}

fn formula_to_legacy_guard_term(formula: IrFormula) -> Option<IrTerm> {
    match formula {
        IrFormula::Atomic { name, args } => Some(IrTerm::Ctor {
            name: cf_head(&name),
            args,
        }),
        IrFormula::And { operands } => formula_operands_to_term("cf_and", operands),
        IrFormula::Or { operands } => formula_operands_to_term("cf_or", operands),
        IrFormula::Not { operands } => formula_operands_to_term("cf_not", operands),
        IrFormula::Implies { operands } => formula_operands_to_term("cf_implies", operands),
        IrFormula::Forall { .. } | IrFormula::Exists { .. } | IrFormula::Choice { .. } => None,
        IrFormula::Substitute { .. }
        | IrFormula::Apply { .. }
        | IrFormula::DivergenceBetween { .. } => None,
    }
}

fn formula_operands_to_term(name: &str, operands: Vec<IrFormula>) -> Option<IrTerm> {
    let args = operands
        .into_iter()
        .map(formula_to_legacy_guard_term)
        .collect::<Option<Vec<_>>>()?;
    Some(IrTerm::Ctor {
        name: name.to_string(),
        args,
    })
}

fn cf_head(name: &str) -> String {
    match name {
        "=" | "eq" => "cf_eq",
        "≠" | "ne" | "neq" => "cf_ne",
        "<" | "lt" => "cf_lt",
        "≤" | "le" | "lte" => "cf_le",
        ">" | "gt" => "cf_gt",
        "≥" | "ge" | "gte" => "cf_ge",
        "and" => "cf_and",
        "or" => "cf_or",
        "not" => "cf_not",
        "implies" => "cf_implies",
        other => return other.to_string(),
    }
    .to_string()
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
