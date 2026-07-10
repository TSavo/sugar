from __future__ import annotations

from typing import Literal, Never, NoReturn

from .coverage_gap_effect import CoverageGapEffect
from .raise_effect import RaiseEffect
from .runtime_effect import RuntimeEffect
from .source_oracle_effect import SourceOracleEffect

# FactoryGapEffect and DigBoundaryEffect are DELETED.
# No-recognizer is panic, not a typed Incomplete arm.
Effect = RaiseEffect | RuntimeEffect | CoverageGapEffect | SourceOracleEffect

EffectStatus = Literal[
    "raise-effect",
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
            RuntimeEffect,
            CoverageGapEffect,
            SourceOracleEffect,
        ),
    ):
        return effect
    raise TypeError(
        "Incomplete.effect must be a typed Effect "
        "(RaiseEffect | RuntimeEffect | CoverageGapEffect | SourceOracleEffect); "
        "FactoryGap/DigBoundary were deleted — the None arm panics"
    )


def effect_kind(effect: Effect) -> str:
    if isinstance(effect, RaiseEffect):
        return "RaiseEffect"
    if isinstance(effect, RuntimeEffect):
        return "RuntimeEffect"
    if isinstance(effect, CoverageGapEffect):
        return "CoverageGap"
    if isinstance(effect, SourceOracleEffect):
        return "SourceOracleEffect"
    return _unhandled_effect(effect)


def effect_reason(effect: Effect) -> str:
    if isinstance(effect, RaiseEffect):
        return effect.reason
    if isinstance(effect, RuntimeEffect):
        return effect.reason
    if isinstance(effect, CoverageGapEffect):
        return effect.reason
    if isinstance(effect, SourceOracleEffect):
        return effect.reason
    return _unhandled_effect(effect)


def effect_status(effect: Effect) -> EffectStatus:
    if isinstance(effect, RaiseEffect):
        return "raise-effect"
    if isinstance(effect, RuntimeEffect):
        return "runtime-effect"
    if isinstance(effect, CoverageGapEffect):
        return "coverage-gap"
    if isinstance(effect, SourceOracleEffect):
        return effect.status
    return _unhandled_effect(effect)


def _unhandled_effect(effect: Never) -> NoReturn:
    raise TypeError(f"unhandled Effect arm: {type(effect).__name__}")
