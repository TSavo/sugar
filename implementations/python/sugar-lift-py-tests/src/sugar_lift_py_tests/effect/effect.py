from __future__ import annotations

from typing import Literal, Never, NoReturn

from .coverage_gap_effect import CoverageGapEffect
from .raise_effect import RaiseEffect, UndeterminedRaiseEffect
from .grouped_raise_effect import GroupedRaiseEffect
from .runtime_effect import RuntimeEffect
from .source_oracle_effect import SourceOracleEffect
from .warning_effect import WarningEffect
from .expectation_not_met_effect import ExpectationNotMetEffect
from .loop_control_effect import LoopControlEffect

# FactoryGapEffect and DigBoundaryEffect are DELETED.
# No-recognizer is panic, not a typed Incomplete arm.
Effect = (
    RaiseEffect
    | UndeterminedRaiseEffect
    | GroupedRaiseEffect
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
            UndeterminedRaiseEffect,
            GroupedRaiseEffect,
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
        "(RaiseEffect | UndeterminedRaiseEffect | WarningEffect | RuntimeEffect | "
        "CoverageGapEffect | SourceOracleEffect); "
        "FactoryGap/DigBoundary were deleted — the None arm panics"
    )


def effect_kind(effect: Effect) -> str:
    if isinstance(effect, GroupedRaiseEffect):
        return "GroupedRaiseEffect"
    if isinstance(effect, RaiseEffect):
        return "RaiseEffect"
    if isinstance(effect, UndeterminedRaiseEffect):
        return "UndeterminedRaiseEffect"
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
    if isinstance(effect, GroupedRaiseEffect):
        return effect.reason
    if isinstance(effect, RaiseEffect):
        return effect.reason
    if isinstance(effect, UndeterminedRaiseEffect):
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
    if isinstance(effect, GroupedRaiseEffect):
        return "raise-effect"
    if isinstance(effect, RaiseEffect):
        return "raise-effect"
    if isinstance(effect, UndeterminedRaiseEffect):
        # Not authenticated; still a raise-shaped halt for routing status only.
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
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner="effect._unhandled_effect",
        blame=f"effect:{type(effect).__name__}",
        observed=f"Effect species {type(effect).__name__} has no dispatch arm",
        requested="a written Effect class with effect_status/effect_reason arms",
        fix=f"write the Effect arm for {type(effect).__name__}; do not raise bare TypeError",
    )
