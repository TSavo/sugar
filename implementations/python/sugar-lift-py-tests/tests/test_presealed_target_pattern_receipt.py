"""RED: TargetPattern canonicalization consumes its eager sealed receipt."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree import backend, binding_state
from sugar_source_tree.binding_state import (
    ConstructedValueCategoryGap,
    _constructed_preimage,
    constructed_value_cid_v2,
)
from sugar_source_tree.nodes import Call, ListComp, SourceUnit, TargetPatternV1
from sugar_source_tree.tree import SourceFile


def _source(helper: str = "sink") -> str:
    return (
        f"result = {helper}([left for (left, right) in items])\n"
        f"other = {helper}([first for (first, second) in more_items])\n"
    )


def _products(helper: str = "sink", *, suffix: str = ""):
    source = _source(helper) + suffix
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, f"{helper}.py", blake3_512_of(source.encode())),
        construction_context=context,
    )
    calls = tuple(node for node in tree.nodes() if isinstance(node, Call))
    comprehensions = tuple(node for node in tree.nodes() if isinstance(node, ListComp))
    assert len(calls) == len(comprehensions) == 2
    sugars = tuple(call._construct_sugar() for call in calls)
    patterns = tuple(sugar.args[0].generators[0].target_pattern for sugar in sugars)
    assert all(type(pattern) is TargetPatternV1 for pattern in patterns)
    return tree, comprehensions, sugars, patterns


def _forbid_late_work(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("presealed TargetPattern canonicalization did late work")

    monkeypatch.setattr(binding_state, "node_construction_shape_cid", forbidden)
    monkeypatch.setattr(backend, "materialize", forbidden)
    monkeypatch.setattr(
        binding_state.ConstructionTestimonyReporterV1,
        "present_construction",
        forbidden,
    )


@pytest.mark.parametrize("helper", ("sink", "unrelated_renamed"))
def test_presealed_pattern_receipt_canonicalizes_without_late_work(
    helper, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree, _comprehensions, sugars, patterns = _products(helper)
    pattern = patterns[0]
    expected_source_cid = tree.unit.source_cid
    expected_consumer = pattern.consumer_occurrence.fragment.seal()
    expected_target = pattern.target_occurrence.fragment.seal()
    expected_leaves = tuple(
        (leaf.fragment.seal(), binding_state.node_construction_shape_cid(leaf))
        for leaf in pattern.leaves
    )
    expected_coordinates = tuple(item.cid for item in pattern.coordinates)
    _forbid_late_work(monkeypatch)

    pattern_preimage = _constructed_preimage(pattern)
    pattern_cid = constructed_value_cid_v2(pattern)
    callsite_cid = constructed_value_cid_v2(sugars[0])
    encoded = json.dumps(pattern_preimage, sort_keys=True)

    assert pattern_cid.startswith("blake3-512:")
    assert callsite_cid.startswith("blake3-512:")
    assert expected_source_cid in encoded
    assert expected_consumer.cid in encoded
    assert expected_target.cid in encoded
    for memento, shape_cid in expected_leaves:
        assert memento.cid in encoded
        assert shape_cid in encoded
    for coordinate_cid in expected_coordinates:
        assert coordinate_cid in encoded


def _assert_loud(pattern: TargetPatternV1) -> None:
    with pytest.raises(ConstructedValueCategoryGap):
        constructed_value_cid_v2(pattern)


@pytest.mark.parametrize(
    "axis",
    (
        "missing-receipt",
        "pre-roster-mint",
        "foreign-source",
        "foreign-consumer",
        "foreign-target",
        "reordered-leaves",
        "missing-leaf",
        "wrong-binding-coordinate",
        "reminted-pattern-receipt",
    ),
)
def test_unowned_or_cross_wired_target_pattern_receipts_stay_loud(axis) -> None:
    tree, comprehensions, _sugars, patterns = _products()
    exact, other = patterns

    if axis == "missing-receipt":
        candidate = TargetPatternV1(
            exact.source_unit,
            exact.consumer_occurrence,
            exact.target_occurrence,
            exact.leaves,
            exact.coordinates,
        )
    elif axis == "pre-roster-mint":
        source = tree.unit.source
        pre_roster_unit = SourceUnit(
            filename="pre_roster.py",
            source=source,
            source_cid=blake3_512_of(source.encode()),
        )
        candidate = TargetPatternV1(
            pre_roster_unit,
            exact.consumer_occurrence,
            exact.target_occurrence,
            exact.leaves,
            exact.coordinates,
        )
    elif axis == "foreign-source":
        foreign = _products(suffix="# foreign authenticated bytes\n")[0]
        candidate = replace(exact, source_unit=foreign.unit)
    elif axis == "foreign-consumer":
        candidate = replace(exact, consumer_occurrence=comprehensions[1])
    elif axis == "foreign-target":
        candidate = replace(exact, target_occurrence=other.target_occurrence)
    elif axis == "reordered-leaves":
        candidate = replace(exact, leaves=tuple(reversed(exact.leaves)))
    elif axis == "missing-leaf":
        candidate = replace(exact, leaves=exact.leaves[:-1])
    elif axis == "wrong-binding-coordinate":
        candidate = replace(
            exact, coordinates=(other.coordinates[0], exact.coordinates[1])
        )
    else:
        candidate = replace(exact)

    _assert_loud(candidate)


@dataclass
class _UnrelatedMutableDataclass:
    value: int


def test_generic_mutable_dataclass_remains_loud() -> None:
    with pytest.raises(ConstructedValueCategoryGap) as gap:
        constructed_value_cid_v2(_UnrelatedMutableDataclass(1))
    assert "MUTABLE dataclass" in str(gap.value)
