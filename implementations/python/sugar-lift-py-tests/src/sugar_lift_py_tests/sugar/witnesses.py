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


SugarWitnesses = SugarWitnessPair | tuple[SugarWitnessPair, ...]


@dataclass(frozen=True)
class PendingWitnesses:
    """Typed staging marker for a registrable sugar awaiting witness enrollment."""

    sugar_name: str
    module: str
    reason: str = "witness enrollment pending"


@dataclass(frozen=True)
class NotVerdictBearing:
    """A non-FOL opt-out must be justified by a marked floor type."""

    sugar_name: str
    floor_name: str
    reason: str
