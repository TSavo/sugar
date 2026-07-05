// SPDX-License-Identifier: MIT OR Apache-2.0

use std::rc::Rc;

use sugar_ir_symbolic::Term;

#[derive(Clone)]
pub struct SymbolicValue {
    term: Rc<Term>,
}

impl SymbolicValue {
    pub fn new(term: Rc<Term>) -> Self {
        Self { term }
    }

    pub fn from_term(term: Rc<Term>) -> Option<Self> {
        match term.as_ref() {
            Term::Var { .. } => Some(Self { term }),
            _ => None,
        }
    }

    pub fn term(&self) -> &Rc<Term> {
        &self.term
    }

    pub fn into_term(self) -> Rc<Term> {
        self.term
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn explicit_symbolic_value_can_carry_composed_sort_neutral_term() {
        let term = Rc::new(Term::Ctor {
            name: "cf_ite".to_string(),
            args: vec![
                Rc::new(Term::Var {
                    name: "guard".to_string(),
                }),
                Rc::new(Term::Var {
                    name: "then_value".to_string(),
                }),
                Rc::new(Term::Var {
                    name: "else_value".to_string(),
                }),
            ],
        });

        let symbolic = SymbolicValue::new(Rc::clone(&term));
        let Term::Ctor { name, args } = symbolic.term().as_ref() else {
            panic!("explicit SymbolicValue constructor should carry the composed term");
        };
        assert_eq!(name, "cf_ite");
        assert_eq!(args.len(), 3);
    }

    #[test]
    fn automatic_symbolic_value_recognition_stays_conservative() {
        let term = Rc::new(Term::Const {
            value: sugar_ir_symbolic::ConstValue::Int(1),
            sort: sugar_ir_symbolic::Sort::int(),
        });

        assert!(SymbolicValue::from_term(term).is_none());
    }
}
