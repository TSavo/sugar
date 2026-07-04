from __future__ import annotations

from typing import Never, NoReturn

from .coverage_gap_effect import CoverageGapEffect
from .dig_refusal_effect import DigRefusalEffect
from .factory_gap_effect import FactoryGapEffect
from .raise_effect import RaiseEffect
from .runtime_effect import RuntimeEffect
from .source_oracle_effect import SourceOracleEffect

Effect = (
    RaiseEffect
    | RuntimeEffect
    | CoverageGapEffect
    | FactoryGapEffect
    | DigRefusalEffect
    | SourceOracleEffect
)


def require_effect(effect: object) -> Effect:
    if isinstance(
        effect,
        (
            RaiseEffect,
            RuntimeEffect,
            CoverageGapEffect,
            FactoryGapEffect,
            DigRefusalEffect,
            SourceOracleEffect,
        ),
    ):
        return effect
    raise TypeError(
        "Incomplete.effect must be a typed Effect "
        "(RaiseEffect | RuntimeEffect | CoverageGapEffect | FactoryGapEffect | "
        "DigRefusalEffect | SourceOracleEffect)"
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
    if isinstance(effect, DigRefusalEffect):
        return "DigRefusal"
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
    if isinstance(effect, DigRefusalEffect):
        return effect.reason
    if isinstance(effect, SourceOracleEffect):
        return effect.reason
    return _unhandled_effect(effect)


def effect_status(effect: Effect) -> str:
    if isinstance(effect, RaiseEffect):
        return "refused"
    if isinstance(effect, RuntimeEffect):
        return "refused"
    if isinstance(effect, CoverageGapEffect):
        return "refused"
    if isinstance(effect, FactoryGapEffect):
        return "refused"
    if isinstance(effect, DigRefusalEffect):
        return "refused"
    if isinstance(effect, SourceOracleEffect):
        return effect.status
    return _unhandled_effect(effect)


def _unhandled_effect(effect: Never) -> NoReturn:
    raise TypeError(f"unhandled Effect arm: {type(effect).__name__}")
