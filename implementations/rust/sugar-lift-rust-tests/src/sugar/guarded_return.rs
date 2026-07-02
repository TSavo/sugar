// SPDX-License-Identifier: Apache-2.0
//
// GuardedReturn floor.
//
// Python reference: `floor/guarded_return.py` carries `(guards, value)` and the
// control-flow guard operation lowers it as `implies(and(guards), out == value)`.
// Rust keeps the same mechanism but represents it as a closed struct consumed by
// BlockSugar/IfSugar rather than Python's runtime `isinstance` dispatch.

use std::rc::Rc;

use sugar_ir_symbolic::{and_, atomic_, eq, implies, make_var, Formula, Term};

#[derive(Clone)]
pub(crate) struct GuardedReturn {
    pub(crate) guards: Vec<Rc<Formula>>,
    pub(crate) term: Rc<Term>,
}

impl GuardedReturn {
    pub(crate) fn new(guards: Vec<Rc<Formula>>, term: Rc<Term>) -> Self {
        Self { guards, term }
    }

    pub(crate) fn with_prefix(&self, prefix: &[Rc<Formula>]) -> Self {
        let mut guards = prefix.to_vec();
        guards.extend(self.guards.iter().cloned());
        Self {
            guards,
            term: self.term.clone(),
        }
    }
}

pub(crate) fn guarded_returns_to_formula(guarded: Vec<GuardedReturn>) -> Option<Rc<Formula>> {
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
