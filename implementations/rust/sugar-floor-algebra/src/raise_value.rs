// SPDX-License-Identifier: Apache-2.0

use crate::Effect;

#[derive(Clone)]
pub struct RaiseValue {
    effect: Effect,
}

impl RaiseValue {
    pub fn from_effect(effect: Effect) -> Option<Self> {
        is_raise_like_effect(&effect).then(|| Self::new(effect))
    }

    pub fn new(effect: Effect) -> Self {
        Self { effect }
    }

    pub fn effect(&self) -> &Effect {
        &self.effect
    }
}

pub fn is_raise_like_effect(effect: &Effect) -> bool {
    matches!(
        effect,
        Effect::PanicMacro { .. } | Effect::LiteralPanic { .. } | Effect::ControlFlow { .. }
    )
}
