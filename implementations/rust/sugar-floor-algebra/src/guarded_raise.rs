// SPDX-License-Identifier: Apache-2.0

use std::rc::Rc;

use sugar_ir_symbolic::Formula;

use crate::{Effect, RaiseValue};

#[derive(Clone)]
pub struct GuardedRaise {
    guards: Vec<Rc<Formula>>,
    raise: RaiseValue,
}

impl GuardedRaise {
    pub fn new(guards: Vec<Rc<Formula>>, effect: Effect) -> Self {
        Self {
            guards,
            raise: RaiseValue::new(effect),
        }
    }

    pub fn from_raise(guards: Vec<Rc<Formula>>, raise: RaiseValue) -> Self {
        Self { guards, raise }
    }

    pub fn guards(&self) -> &[Rc<Formula>] {
        &self.guards
    }

    pub fn effect(&self) -> &Effect {
        self.raise.effect()
    }

    pub fn with_prefix(&self, prefix: &[Rc<Formula>]) -> Self {
        let mut guards = prefix.to_vec();
        guards.extend(self.guards.iter().cloned());
        Self {
            guards,
            raise: self.raise.clone(),
        }
    }
}
