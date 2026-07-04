// SPDX-License-Identifier: Apache-2.0
//
// GuardedRaise floor.
//
// Python reference: `floor/guarded_raise.py` carries `(guards, effect, scope)`;
// route_raises treats it like a RaiseValue while preserving the guards around
// any matching handler body. Rust keeps the same data shape in a closed
// statement floor.

use std::rc::Rc;

use sugar_ir_symbolic::Formula;

use crate::sugar::raise_value::RaiseValue;
use crate::{Effect, TemporalScope};

#[derive(Clone)]
pub(crate) struct GuardedRaise {
    guards: Vec<Rc<Formula>>,
    raise: RaiseValue,
}

impl GuardedRaise {
    pub(crate) fn from_raise(guards: Vec<Rc<Formula>>, raise: RaiseValue) -> Self {
        Self { guards, raise }
    }

    pub(crate) fn guards(&self) -> &[Rc<Formula>] {
        &self.guards
    }

    pub(crate) fn effect(&self) -> &Effect {
        self.raise.effect()
    }

    pub(crate) fn scope(&self) -> &TemporalScope {
        self.raise.scope()
    }

    pub(crate) fn with_prefix(&self, prefix: &[Rc<Formula>]) -> Self {
        let mut guards = prefix.to_vec();
        guards.extend(self.guards.iter().cloned());
        Self {
            guards,
            raise: self.raise.clone(),
        }
    }
}
