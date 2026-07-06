from __future__ import annotations

from typing import Literal, Never, NoReturn

from .coverage_gap_effect import CoverageGapEffect
from .dig_refusal_effect import DigBoundaryEffect
from .factory_gap_effect import FactoryGapEffect
from .raise_effect import RaiseEffect
from .runtime_effect import RuntimeEffect
from .source_oracle_effect import SourceOracleEffect

Effect = (
    RaiseEffect
    | RuntimeEffect
    | CoverageGapEffect
    | FactoryGapEffect
    | DigBoundaryEffect
    | SourceOracleEffect
)

EffectStatus = Literal[
    "raise-effect",
    "runtime-effect",
    "coverage-gap",
    "factory-gap",
    "dig-boundary",
    # #3632 legacy: DigBoundaryEffect (né DigRefusalEffect) used to report
    # this status as "dig-refusal". Kept in the type for read compatibility
    # with any status value produced by an older kit build.
    "dig-refusal",
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
            FactoryGapEffect,
            DigBoundaryEffect,
            SourceOracleEffect,
        ),
    ):
        return effect
    raise TypeError(
        "Incomplete.effect must be a typed Effect "
        "(RaiseEffect | RuntimeEffect | CoverageGapEffect | FactoryGapEffect | "
        "DigBoundaryEffect | SourceOracleEffect)"
    )


def effect_kind(effect: Effect) -> str:
    if isinstance(effect, RaiseEffect):
        return "RaiseEffect"
    if isinstance(effect, RuntimeEffect):
        return "RuntimeEffect"
    if isinstance(effect, CoverageGapEffect):
        return "CoverageGap"
    if isinstance(effect, FactoryGapEffect):
        return "FactoryGap"
    if isinstance(effect, DigBoundaryEffect):
        return "DigBoundary"
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
    if isinstance(effect, FactoryGapEffect):
        return effect.reason
    if isinstance(effect, DigBoundaryEffect):
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
    if isinstance(effect, FactoryGapEffect):
        return "factory-gap"
    if isinstance(effect, DigBoundaryEffect):
        return "dig-boundary"
    if isinstance(effect, SourceOracleEffect):
        return effect.status
    return _unhandled_effect(effect)


def _unhandled_effect(effect: Never) -> NoReturn:
    raise TypeError(f"unhandled Effect arm: {type(effect).__name__}")


# Compatibility alias: pre-#3632 code imports `DigRefusalEffect`.
DigRefusalEffect = DigBoundaryEffect
