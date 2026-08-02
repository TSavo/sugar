"""Sealed grounds — closed 'why this could not be decided' (no free-text exemption).

Shared shell for:
  - **RefusalDecidability** — named refusals / construction panics (this module)
  - **NotVerdictBearing** (mr_white) — same idea: replace ``reason: str`` with a
    closed ground that ``holds(world)``. Opt-out kinds land here as siblings
    later; do not invent a second vocabulary.

------------------------------------------------------------------------
Criterion 3 — R split (law; see docs/path-forward.md)

  Source-visible constructs; source-undecidable refuses **naming the artifact
  it cannot see**.

  R_kit_incomplete
      Count of mints whose ground is KitConstructionIncomplete.
      Drains by writing sugar/floor, OR by proving a hierarchy lie and deleting
      the false arm. NOT C3 finality.

  R_source_undecidable_refusals
      Count of mints with runtime sealed grounds that holds(world), plus residual
      classes enrolled as honestly undecidable (CM resolution via
      EnrolledDemandUnresolved, …). THIS is C3.

  A refusal that exists because a type was wrong is a **defect wearing a
  refusal**. It drains by fixing the type, never by improving the prose.
  Naming a type in observed is not the same as being legitimately undecidable
  (#6988 auditor would have banked ~159 hierarchy lies as good C3).

  KitConstructionIncomplete.holds() is always True on purpose: the incompleteness
  is the kit. It must not be the only door for honest undecidable residuals —
  those mint EnrolledDemandUnresolved (or a sibling runtime ground).

  R_refusals_over_decidable_source = mints where holds(world) is false.
  That is a floor (must stay empty), not progress to lower by softening refusals.

  Pure re-attempt-and-see without a sealed ground is ill-defined and forbidden:
  success does not prove the refused path was wrong.
------------------------------------------------------------------------

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


@dataclass(frozen=True)
class EnrolledDemandArtifact:
    """Enrolled demand whose derivation returned a structural gap, not a ref.

    The artifact the refusal cannot see is the source-derived contract ref
    (``expected_ref_type``) for this demand — not a free-text "undecidable".
    """

    demand_family: str
    """Closed family key: context-manager | import-value-use | opaque-call | …"""

    demand_cid: str
    use_site: str
    gap_kind: str
    """Structural gap key from the resolution table vocabulary (never a symbol)."""

    expected_ref_type: str
    """Type name of the ref that would close the demand (e.g. ContextManagerContractRefV1)."""


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
class EnrolledDemandUnresolved:
    """Enrolled demand still a resolution gap — honest source-undecidable residual.

    C3 door for CM resolution (and sibling resolution tables). Distinct from
    KitConstructionIncomplete: derivation **ran**; the table has a structural
    gap, not a contract ref. ``holds`` is false when a ref is present — minting
    a refusal then would be refusing over decidable/resolvable source.

    world key: ``enrolled_demand_unresolved`` bool (True ⇒ still a gap).
    """

    artifact: EnrolledDemandArtifact

    def holds(self, world: Mapping[str, Any] | None = None) -> bool:
        if world is None or "enrolled_demand_unresolved" not in world:
            raise TypeError(
                "EnrolledDemandUnresolved.holds requires world["
                "'enrolled_demand_unresolved']=bool at mint "
                "(True when resolution table still has a gap for this demand, "
                "not a contract ref)"
            )
        return bool(world["enrolled_demand_unresolved"])


@dataclass(frozen=True)
class KitConstructionIncomplete:
    """Legal construction panic: OUR incomplete sugar/floor arm.

    Counts under **R_kit_incomplete**, not R_source_undecidable_refusals.
    ``holds`` is always True — the incompleteness is the kit, not a claim that
    source was undecidable. Hierarchy-lie bugs that panic here are defects
    wearing refusals; drain by fixing the type, not by renaming observed.

    Honest undecidable residuals (CM resolution gaps, …) must NOT default here:
    mint EnrolledDemandUnresolved (or a sibling runtime ground) instead.
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
    EnrolledDemandUnresolved,
    KitConstructionIncomplete,
]

_REFUSAL_KINDS = (
    RuntimeTypeUndecided,
    KeyEqualityUndecided,
    FormalDemandUndischarged,
    ConflictingObligation,
    EnrolledDemandUnresolved,
    KitConstructionIncomplete,
)

_GROUND_NAMES = (
    "RuntimeTypeUndecided | KeyEqualityUndecided | "
    "FormalDemandUndischarged | ConflictingObligation | "
    "EnrolledDemandUnresolved | KitConstructionIncomplete"
)


def is_refusal_decidability(value: object) -> bool:
    return isinstance(value, _REFUSAL_KINDS)


def kit_incomplete(*, owner: str, observed: object) -> KitConstructionIncomplete:
    """One door for ordinary construction-panic sites (OUR missing arm).

    R_kit_incomplete — not C3 finality. Prefer EnrolledDemandUnresolved when
    the residual is an enrolled demand whose derivation returned a gap.
    """
    return KitConstructionIncomplete(
        artifact=KitIncompleteArtifact(
            owner=owner,
            observed_shape=observed if isinstance(observed, str) else repr(observed),
        )
    )


def enrolled_demand_unresolved(
    *,
    demand_family: str,
    demand_cid: str,
    use_site: str,
    gap_kind: str,
    expected_ref_type: str,
) -> EnrolledDemandUnresolved:
    """One door for resolution-table gaps (CM, import-value-use, opaque-call, …).

    R_source_undecidable_refusals — C3. Mint only with world where
    enrolled_demand_unresolved is True.
    """
    return EnrolledDemandUnresolved(
        artifact=EnrolledDemandArtifact(
            demand_family=demand_family,
            demand_cid=demand_cid,
            use_site=use_site,
            gap_kind=gap_kind,
            expected_ref_type=expected_ref_type,
        )
    )


def require_refusal_ground_holds(
    decidability: RefusalDecidability,
    world: Mapping[str, Any] | None = None,
) -> None:
    """Mint door: sealed ground must hold, or the refusal is over-decidable.

    - ``KitConstructionIncomplete``: always holds (no world). Counts as kit R.
    - Runtime grounds (incl. EnrolledDemandUnresolved): require ``world`` and
      ``holds(world) is True``.
    - Free-text / unknown types: TypeError (unconstructible).
    """
    if not is_refusal_decidability(decidability):
        raise TypeError(
            "RefusalDecidability must be a closed sealed ground: "
            f"observed={type(decidability).__name__} "
            f"replacement={_GROUND_NAMES}"
        )
    if isinstance(decidability, KitConstructionIncomplete):
        return
    if world is None:
        raise TypeError(
            f"{type(decidability).__name__} mint requires world= for holds(); "
            "kit-incomplete sites use KitConstructionIncomplete instead; "
            "CM / resolution gaps use EnrolledDemandUnresolved + world"
        )
    if not decidability.holds(world):
        raise TypeError(
            "RefusalDecidability ground does not hold — refused over decidable "
            f"source. ground={type(decidability).__name__} "
            "replacement=construct the value, or mint only when holds(world)"
        )
