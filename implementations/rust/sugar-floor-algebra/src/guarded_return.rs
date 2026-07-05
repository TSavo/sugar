// SPDX-License-Identifier: MIT OR Apache-2.0

use std::rc::Rc;

use sugar_ir_symbolic::{and_, atomic_, eq, implies, make_var, Formula, Term};

#[derive(Clone)]
pub struct GuardedReturn {
    guards: Vec<Rc<Formula>>,
    term: Rc<Term>,
}

impl GuardedReturn {
    pub fn new(guards: Vec<Rc<Formula>>, term: Rc<Term>) -> Self {
        Self { guards, term }
    }

    pub fn guards(&self) -> &[Rc<Formula>] {
        &self.guards
    }

    pub fn term(&self) -> &Rc<Term> {
        &self.term
    }

    pub fn into_parts(self) -> (Vec<Rc<Formula>>, Rc<Term>) {
        (self.guards, self.term)
    }

    pub fn with_prefix(&self, prefix: &[Rc<Formula>]) -> Self {
        let mut guards = prefix.to_vec();
        guards.extend(self.guards.iter().cloned());
        Self {
            guards,
            term: self.term.clone(),
        }
    }
}

pub fn guarded_returns_to_formula(guarded: Vec<GuardedReturn>) -> Option<Rc<Formula>> {
    if guarded.is_empty() {
        return None;
    }
    let out = make_var("out");
    Some(and_(
        guarded
            .into_iter()
            .map(|guarded_return| {
                let guard: Rc<Formula> = match guarded_return.guards.len() {
                    0 => atomic_("true", vec![]),
                    1 => guarded_return.guards.into_iter().next().unwrap(),
                    _ => and_(guarded_return.guards),
                };
                implies(guard, eq(out.clone(), guarded_return.term))
            })
            .collect(),
    ))
}
