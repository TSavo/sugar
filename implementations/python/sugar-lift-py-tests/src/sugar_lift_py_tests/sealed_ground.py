"""Sealed grounds — closed 'why this could not be decided' (no free-text exemption).

Shared shell for:
  - **RefusalDecidability** — named refusals / construction panics (this module)
  - **NotVerdictBearing** (mr_white) — same idea: replace ``reason: str`` with a
    closed ground that ``holds(world)``. Opt-out kinds land here as siblings
    later; do not invent a second vocabulary.

Law (Criterion 3 axis 2):
  A refusal is final only when its ground ``holds(world)``.
  ``R_refusals_over_decidable_source`` = count of mints where the ground does
  not hold — a MEASUREMENT, not a static guess.

  Pure re-attempt-and-see without a sealed ground is ill-defined and forbidden:
  success does not prove the refused path was wrong.

Not the board.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Union

# ---------------------------------------------------------------------------
# Artifacts — what is invisible / incomplete (typed payload, not prose alone)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FloorRuntimeTypeArtifact:
    """Receiver/operand runtime type not source-decided."""

    floor_type_name: str
    site: str | None = None


@dataclass(frozen=True)
class MappingKeyEqualityArtifact:
    """Whether a key equals a stored mapping key is undecided."""

    key_type_name: str
    mapping_type_name: str
    site: str | None = None


@dataclass(frozen=True)
class FormalDemandArtifact:
    """Native-operation demand still undischarged at a boundary."""

    carrier_type_name: str
    demand_type_name: str
    site: str | None = None


@dataclass(frozen=True)
class ObligationCoordinateArtifact:
    """Two unequal obligations claim the same source-call coordinate."""

    coordinate: str
    existing_type_name: str
    new_type_name: str


@dataclass(frozen=True)
class KitIncompleteArtifact:
    """OUR missing match arm / law — construction incomplete, not runtime undecidable."""

    owner: str
    observed_shape: str


# ---------------------------------------------------------------------------
# RefusalDecidability — closed set (extend only with a floor move)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeTypeUndecided:
    """Source has not decided the floor's runtime type; neither edge is honest."""

    artifact: FloorRuntimeTypeArtifact

    def holds(self, world: Mapping[str, Any] | None = None) -> bool:
        if world is None or "runtime_type_is_decided" not in world:
            raise TypeError(
                "RuntimeTypeUndecided.holds requires world["
                "'runtime_type_is_decided']=bool at mint"
            )
        return not bool(world["runtime_type_is_decided"])


@dataclass(frozen=True)
class KeyEqualityUndecided:
    """At least one mapping-key equality probe returned undecided (None)."""

    artifact: MappingKeyEqualityArtifact

    def holds(self, world: Mapping[str, Any] | None = None) -> bool:
        if world is None or "key_equality_undecided" not in world:
            raise TypeError(
                "KeyEqualityUndecided.holds requires world["
                "'key_equality_undecided']=bool at mint"
            )
        return bool(world["key_equality_undecided"])


@dataclass(frozen=True)
class FormalDemandUndischarged:
    """Carrier still holds undischarged formal demand at exit-set boundary."""

    artifact: FormalDemandArtifact

    def holds(self, world: Mapping[str, Any] | None = None) -> bool:
        if world is None or "formal_demand_undischarged" not in world:
            raise TypeError(
                "FormalDemandUndischarged.holds requires world["
                "'formal_demand_undischarged']=bool at mint"
            )
        return bool(world["formal_demand_undischarged"])


@dataclass(frozen=True)
class ConflictingObligation:
    """Existing opaque obligation disagrees with the new one at a coordinate."""

    artifact: ObligationCoordinateArtifact

    def holds(self, world: Mapping[str, Any] | None = None) -> bool:
        if world is None or "obligations_conflict" not in world:
            raise TypeError(
                "ConflictingObligation.holds requires world["
                "'obligations_conflict']=bool at mint"
            )
        return bool(world["obligations_conflict"])


@dataclass(frozen=True)
class KitConstructionIncomplete:
    """Legal construction panic: OUR incomplete sugar/floor arm.

    ``holds`` is always True — the incompleteness is the kit, not a false
    claim that source was undecidable. Distinct from runtime-undecided grounds.
    """

    artifact: KitIncompleteArtifact

    def holds(self, world: Mapping[str, Any] | None = None) -> bool:
        del world
        return True


RefusalDecidability = Union[
    RuntimeTypeUndecided,
    KeyEqualityUndecided,
    FormalDemandUndischarged,
    ConflictingObligation,
    KitConstructionIncomplete,
]

_REFUSAL_KINDS = (
    RuntimeTypeUndecided,
    KeyEqualityUndecided,
    FormalDemandUndischarged,
    ConflictingObligation,
    KitConstructionIncomplete,
)


def is_refusal_decidability(value: object) -> bool:
    return isinstance(value, _REFUSAL_KINDS)


def kit_incomplete(*, owner: str, observed: object) -> KitConstructionIncomplete:
    """One door for ordinary construction-panic sites (OUR missing arm)."""
    return KitConstructionIncomplete(
        artifact=KitIncompleteArtifact(
            owner=owner,
            observed_shape=observed if isinstance(observed, str) else repr(observed),
        )
    )


def require_refusal_ground_holds(
    decidability: RefusalDecidability,
    world: Mapping[str, Any] | None = None,
) -> None:
    """Mint door: sealed ground must hold, or the refusal is over-decidable.

    - ``KitConstructionIncomplete``: always holds (no world).
    - Runtime grounds: require ``world`` and ``holds(world) is True``.
    - Free-text / unknown types: TypeError (unconstructible).
    """
    if not is_refusal_decidability(decidability):
        raise TypeError(
            "RefusalDecidability must be a closed sealed ground: "
            f"observed={type(decidability).__name__} "
            "replacement=RuntimeTypeUndecided | KeyEqualityUndecided | "
            "FormalDemandUndischarged | ConflictingObligation | "
            "KitConstructionIncomplete"
        )
    if isinstance(decidability, KitConstructionIncomplete):
        return
    if world is None:
        raise TypeError(
            f"{type(decidability).__name__} mint requires world= for holds(); "
            "kit-incomplete sites use KitConstructionIncomplete instead"
        )
    if not decidability.holds(world):
        raise TypeError(
            "RefusalDecidability ground does not hold — refused over decidable "
            f"source. ground={type(decidability).__name__} "
            "replacement=construct the value, or mint only when holds(world)"
        )
