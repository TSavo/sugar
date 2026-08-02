"""Teeth for RefusalDecidability sealed grounds (Criterion 3 axis-2 unblock)."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
from sugar_lift_py_tests.gap.panic import construction_panic_gap, ConstructionPanic
from sugar_lift_py_tests.sealed_ground import (
    FloorRuntimeTypeArtifact,
    FormalDemandArtifact,
    FormalDemandUndischarged,
    KeyEqualityUndecided,
    KitConstructionIncomplete,
    KitIncompleteArtifact,
    MappingKeyEqualityArtifact,
    RuntimeTypeUndecided,
    is_refusal_decidability,
    kit_incomplete,
    require_refusal_ground_holds,
)


def test_kit_incomplete_always_holds() -> None:
    ground = kit_incomplete(owner="Owner", observed="shape")
    assert isinstance(ground, KitConstructionIncomplete)
    assert ground.holds() is True
    assert ground.holds({}) is True
    require_refusal_ground_holds(ground)


def test_runtime_type_undecided_holds_only_when_undecided() -> None:
    ground = RuntimeTypeUndecided(
        artifact=FloorRuntimeTypeArtifact(floor_type_name="SymbolicValue")
    )
    assert ground.holds({"runtime_type_is_decided": False}) is True
    assert ground.holds({"runtime_type_is_decided": True}) is False
    require_refusal_ground_holds(ground, {"runtime_type_is_decided": False})
    with pytest.raises(TypeError, match="does not hold"):
        require_refusal_ground_holds(ground, {"runtime_type_is_decided": True})


def test_runtime_ground_requires_world_at_mint() -> None:
    ground = RuntimeTypeUndecided(
        artifact=FloorRuntimeTypeArtifact(floor_type_name="X")
    )
    with pytest.raises(TypeError, match="requires world"):
        require_refusal_ground_holds(ground, world=None)


def test_free_text_is_not_a_ground() -> None:
    assert is_refusal_decidability("undecidable") is False
    with pytest.raises(TypeError, match="closed sealed ground"):
        require_refusal_ground_holds("undecidable")  # type: ignore[arg-type]


def test_construction_gap_defaults_to_kit_incomplete() -> None:
    gap = ConstructionGap(
        owner="law",
        blame="b.py:1:0",
        observed="missing arm",
        requested="floor",
        fix="write more Floor",
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )
    assert isinstance(gap.decidability, KitConstructionIncomplete)
    assert gap.decidability.artifact.owner == "law"


def test_construction_panic_gap_refuses_over_decidable_source() -> None:
    ground = KeyEqualityUndecided(
        artifact=MappingKeyEqualityArtifact(
            key_type_name="TermValue",
            mapping_type_name="DictValue",
        )
    )
    with pytest.raises(TypeError, match="does not hold"):
        construction_panic_gap(
            owner="test",
            blame="t.py:1:0",
            observed="key eq",
            requested="decided",
            fix="construct",
            decidability=ground,
            world={"key_equality_undecided": False},
        )


def test_construction_panic_gap_defaults_sealed_and_raises_panic() -> None:
    with pytest.raises(ConstructionPanic):
        construction_panic_gap(
            owner="test",
            blame="t.py:1:0",
            observed="no arm",
            requested="arm",
            fix="write",
        )


def test_formal_demand_ground() -> None:
    ground = FormalDemandUndischarged(
        artifact=FormalDemandArtifact(
            carrier_type_name="NativeOperationExitCarrierV1",
            demand_type_name="Demand",
        )
    )
    assert ground.holds({"formal_demand_undischarged": True})
    with pytest.raises(TypeError, match="does not hold"):
        require_refusal_ground_holds(
            ground, {"formal_demand_undischarged": False}
        )
