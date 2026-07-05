from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Verdict = Literal["sat", "unsat"]


@dataclass(frozen=True)
class WitnessSource:
    source: str
    expected: Verdict


@dataclass(frozen=True)
class SugarWitnessPair:
    """One production witness pair for a verdict-bearing sugar."""

    name: str
    owner_sugar: str
    family: str
    truthful: WitnessSource
    lying: WitnessSource


@dataclass(frozen=True)
class TypedRedEffectExpectation:
    effect_class: str
    reason_needle: str
    blame_needle: str


@dataclass(frozen=True)
class EffectWitnessSource:
    source: str
    expectation: TypedRedEffectExpectation
    expected_match: bool
    function_name: str = "A"


@dataclass(frozen=True)
class SugarRedEffectWitnessPair:
    """One production witness pair for a lawful typed-red sugar."""

    name: str
    owner_sugar: str
    family: str
    truthful: EffectWitnessSource
    lying: EffectWitnessSource


@dataclass(frozen=True)
class NotVerdictBearing:
    """A non-FOL opt-out must be justified by a marked floor type."""

    sugar_name: str
    floor_name: str
    reason: str


SugarWitnesses = (
    SugarWitnessPair
    | SugarRedEffectWitnessPair
    | tuple[SugarWitnessPair, ...]
    | NotVerdictBearing
    | tuple[SugarWitnessPair | SugarRedEffectWitnessPair | NotVerdictBearing, ...]
)
