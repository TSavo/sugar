from __future__ import annotations

from typing import Never, NoReturn

from .coverage_gap_effect import CoverageGapEffect
from .raise_effect import RaiseEffect
from .runtime_effect import RuntimeEffect

Effect = RaiseEffect | RuntimeEffect | CoverageGapEffect


def require_effect(effect: object) -> Effect:
    if isinstance(effect, (RaiseEffect, RuntimeEffect, CoverageGapEffect)):
        return effect
    raise TypeError(
        "Incomplete.effect must be a typed Effect "
        "(RaiseEffect | RuntimeEffect | CoverageGapEffect)"
    )


def effect_kind(effect: Effect) -> str:
    if isinstance(effect, RaiseEffect):
        return "RaiseEffect"
    if isinstance(effect, RuntimeEffect):
        return "RuntimeEffect"
    if isinstance(effect, CoverageGapEffect):
        return "CoverageGap"
    return _unhandled_effect(effect)


def effect_reason(effect: Effect) -> str:
    if isinstance(effect, RaiseEffect):
        return effect.reason
    if isinstance(effect, RuntimeEffect):
        return effect.reason
    if isinstance(effect, CoverageGapEffect):
        return effect.reason
    return _unhandled_effect(effect)


def _unhandled_effect(effect: Never) -> NoReturn:
    raise TypeError(f"unhandled Effect arm: {type(effect).__name__}")
