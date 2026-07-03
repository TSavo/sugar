// SPDX-License-Identifier: Apache-2.0
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
    use crate::{refusal_disposition, Disposition, RaiseEffect, RuntimeEffect};
    use sugar_ir_symbolic::num;

    #[test]
    fn typed_raise_effect_family_is_raise_like_but_coverage_gap_is_not() {
        for effect in [
            Effect::Raise(RaiseEffect::Panic {
                boundary: "panic!(\"boom\")".to_string(),
            }),
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
            boundary: "FutureFloor".to_string(),
            reason: "no routing arm".to_string(),
        }));
    }

    #[test]
    fn observable_drop_is_named_runtime_effect_and_not_raise_like() {
        let effect = Effect::Runtime(RuntimeEffect::ObservableDrop {
            boundary: "DropCounter::drop".to_string(),
            reason: "drop-on-panic side effect, runtime, not literal".to_string(),
        });

        assert!(!is_raise_like_effect(&effect));
        let reason = effect.reason();
        assert!(reason.contains("observable Drop effect"));
        assert!(reason.contains("DropCounter::drop"));
        assert_eq!(refusal_disposition(&reason), Disposition::Refused);
    }

    #[test]
    fn finally_over_incomplete_is_named_runtime_effect_and_not_swallowed() {
        let effect = Effect::Runtime(RuntimeEffect::FinallyOverIncomplete {
            boundary: "finally cleanup over incomplete panic".to_string(),
        });

        assert!(!is_raise_like_effect(&effect));
        let reason = effect.reason();
        assert!(reason.contains("finally guarded return over incomplete incoming exit"));
        assert!(reason.contains("finally cleanup over incomplete panic"));
        assert_eq!(refusal_disposition(&reason), Disposition::Refused);
    }
}
