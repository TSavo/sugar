// SPDX-License-Identifier: MIT OR Apache-2.0
//
// RaiseValue floor.
//
// Python reference: `floor/raise_value.py` carries `(effect, scope)` as
// control-flow data so `TrySugar` can route it before residual effects are
// lowered. Rust mirrors that mechanism with an explicit `TemporalScope`
// snapshot; unlike Python, there is no dynamic scope dictionary to attach.

use crate::{Effect, TemporalScope};

#[derive(Clone)]
pub(crate) struct RaiseValue {
    effect: Effect,
    scope: Box<TemporalScope>,
}

impl RaiseValue {
    pub(crate) fn from_effect(effect: Effect, scope: &TemporalScope) -> Option<Self> {
        is_raise_like_effect(&effect).then(|| Self::new(effect, scope.clone()))
    }

    pub(crate) fn new(effect: Effect, scope: TemporalScope) -> Self {
        Self {
            effect,
            scope: Box::new(scope),
        }
    }

    pub(crate) fn effect(&self) -> &Effect {
        &self.effect
    }

    pub(crate) fn scope(&self) -> &TemporalScope {
        &self.scope
    }
}

pub(crate) fn is_raise_like_effect(effect: &Effect) -> bool {
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
    use sugar_ir_symbolic::num;

    #[test]
    fn typed_raise_effect_family_is_raise_like_but_coverage_gap_is_not() {
        for effect in [
            Effect::Raise(RaiseEffect::ResultErr {
                boundary: "fallible()?".to_string(),
            }),
            Effect::Raise(RaiseEffect::EarlyReturnValue {
                boundary: "return Err(e)".to_string(),
                value: num(7),
            }),
        ] {
            assert!(is_raise_like_effect(&effect));
        }

        assert!(!is_raise_like_effect(&Effect::CoverageGap {
            reason: "no routing arm".to_string(),
        }));
    }
}
