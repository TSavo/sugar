from __future__ import annotations

from typing import Literal, Never, NoReturn

from .coverage_gap_effect import CoverageGapEffect
from .raise_effect import RaiseEffect
from .runtime_effect import RuntimeEffect
from .source_oracle_effect import SourceOracleEffect
from .warning_effect import WarningEffect
from .expectation_not_met_effect import ExpectationNotMetEffect
from .loop_control_effect import LoopControlEffect

# FactoryGapEffect and DigBoundaryEffect are DELETED.
# No-recognizer is panic, not a typed Incomplete arm.
Effect = (
    RaiseEffect
    | WarningEffect
    | RuntimeEffect
    | CoverageGapEffect
    | SourceOracleEffect
    | ExpectationNotMetEffect
    | LoopControlEffect
)

EffectStatus = Literal[
    "raise-effect",
    "warning-effect",
    "runtime-effect",
    "coverage-gap",
    "absent",
    "drifted",
]


def require_effect(effect: object) -> Effect:
    if isinstance(
        effect,
        (
            RaiseEffect,
            WarningEffect,
            RuntimeEffect,
            CoverageGapEffect,
            SourceOracleEffect,
            ExpectationNotMetEffect,
            LoopControlEffect,
        ),
    ):
        return effect
    raise TypeError(
        "Incomplete.effect must be a typed Effect "
        "(RaiseEffect | WarningEffect | RuntimeEffect | CoverageGapEffect | SourceOracleEffect); "
        "FactoryGap/DigBoundary were deleted — the None arm panics"
    )


def effect_kind(effect: Effect) -> str:
    if isinstance(effect, RaiseEffect):
        return "RaiseEffect"
    if isinstance(effect, WarningEffect):
        return "WarningEffect"
    if isinstance(effect, RuntimeEffect):
        return "RuntimeEffect"
    if isinstance(effect, CoverageGapEffect):
        return "CoverageGap"
    if isinstance(effect, SourceOracleEffect):
        return "SourceOracleEffect"
    if isinstance(effect, ExpectationNotMetEffect):
        return "ExpectationNotMetEffect"
    if isinstance(effect, LoopControlEffect):
        return "LoopControlEffect"
    return _unhandled_effect(effect)


def effect_reason(effect: Effect) -> str:
    if isinstance(effect, RaiseEffect):
        return effect.reason
    if isinstance(effect, WarningEffect):
        return effect.reason
    if isinstance(effect, RuntimeEffect):
        return effect.reason
    if isinstance(effect, CoverageGapEffect):
        return effect.reason
    if isinstance(effect, SourceOracleEffect):
        return effect.reason
    if isinstance(effect, ExpectationNotMetEffect):
        return effect.reason
    if isinstance(effect, LoopControlEffect):
        return effect.reason
    return _unhandled_effect(effect)


def effect_status(effect: Effect) -> EffectStatus:
    if isinstance(effect, RaiseEffect):
        return "raise-effect"
    if isinstance(effect, WarningEffect):
        return "warning-effect"
    if isinstance(effect, RuntimeEffect):
        return "runtime-effect"
    if isinstance(effect, CoverageGapEffect):
        return "coverage-gap"
    if isinstance(effect, SourceOracleEffect):
        return effect.status
    if isinstance(effect, ExpectationNotMetEffect):
        return "runtime-effect"
    if isinstance(effect, LoopControlEffect):
        return "runtime-effect"
    return _unhandled_effect(effect)


def _unhandled_effect(effect: Never) -> NoReturn:
    raise TypeError(f"unhandled Effect arm: {type(effect).__name__}")
