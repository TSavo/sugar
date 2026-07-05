// SPDX-License-Identifier: MIT OR Apache-2.0

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
        Effect::Raise(_)
            | Effect::PanicMacro { .. }
            | Effect::LiteralPanic { .. }
            | Effect::ControlFlow { .. }
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::RaiseEffect;

    #[test]
    fn typed_result_err_raise_effect_is_raise_like() {
        let effect = Effect::Raise(RaiseEffect::ResultErr {
            boundary: "fallible()?".to_string(),
        });

        assert!(is_raise_like_effect(&effect));
        assert!(RaiseValue::from_effect(effect).is_some());
    }

    #[test]
    fn legacy_panic_and_typed_result_err_are_raise_like_but_coverage_gap_is_not() {
        assert!(is_raise_like_effect(&Effect::PanicMacro {
            boundary: "panic!(\"boom\")".to_string(),
        }));
        assert!(is_raise_like_effect(&Effect::Raise(
            RaiseEffect::ResultErr {
                boundary: "fallible()?".to_string(),
            }
        )));
        assert!(!is_raise_like_effect(&Effect::CoverageGap {
            boundary: "SymbolicFutureFloor".to_string(),
            reason: "no floor arm".to_string(),
        }));
    }
}
