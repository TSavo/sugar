from __future__ import annotations

import tempfile

import pytest

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_provenance import (
    BindingEntryV1 as SealedBindingEntryV1,
    ConstructedValueTestimonyV1,
)
from sugar_source_tree.binding_state import (
    BindingEntryV1,
    BindingStateWireGap,
    LoopProjectedBinding,
    LoopProjectedCompletedFace,
    RuntimeBindingEntryFactoryV1,
    RuntimeBindingEntryGap,
)
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    return next(SourceFile(path_source(path)).functions())


def _entry(source: str = "def arbitrary():\n    renamed = 1\n"):
    function = _function(source)
    assignment = next(node for node in function.walk() if node.kind == "Assign")
    target = assignment.targets[0]
    live_state = assignment.value
    factory = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": function.fragment.seal().to_dict()})
    )
    entry = factory.mint_entry(
        binding_site=target.fragment,
        projection_path=("targets", 0),
        state=live_state,
    )
    return assignment, live_state, entry


def test_runtime_entry_keeps_live_node_and_projects_only_pure_wire():
    assignment, live_state, entry = _entry()
    assert entry.state is live_state
    assert "renamed" not in entry.coordinate.preimage
    with pytest.raises(RuntimeBindingEntryGap, match="testimony unavailable"):
        entry.wire()

    testimony = ConstructedValueTestimonyV1.mint(
        assignment.value.fragment,
        cid_of_json({"kind": "constructed-int", "value": 1}),
    )
    projected = entry.with_testimony(testimony).wire()
    assert set(projected) == {"coordinate", "state"}
    assert "state" in projected and "ref" not in repr(projected)
    assert SealedBindingEntryV1.decode(projected).wire() == projected


def test_projection_reauthenticates_coordinate_and_testimony_cids():
    from dataclasses import replace

    assignment, _live_state, entry = _entry()
    testimony = ConstructedValueTestimonyV1.mint(
        assignment.value.fragment, cid_of_json({"value": 1})
    )
    ready = entry.with_testimony(testimony)
    with pytest.raises(ValueError, match="coordinate CID mismatch"):
        replace(
            ready,
            coordinate=replace(ready.coordinate, cid="blake3-512:stale"),
        ).wire()
    with pytest.raises(ValueError, match="testimony CID mismatch"):
        ready.with_testimony(replace(testimony, cid="blake3-512:stale")).wire()


def test_distinct_occurrences_borrowing_one_span_never_collide():
    assignment, _live_state, _entry_one = _entry()
    factory = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": assignment.fragment.seal().to_dict()})
    )
    first = factory.mint_entry(
        binding_site=assignment.targets[0].fragment,
        projection_path=("targets", 0),
        state=assignment.value,
    )
    second = factory.mint_entry(
        binding_site=assignment.targets[0].fragment,
        projection_path=("targets", 0),
        state=assignment.value,
    )
    assert first.coordinate.cid != second.coordinate.cid


def test_runtime_binding_map_has_one_carrier_not_parallel_name_to_node_state():
    assignment, live_state, entry = _entry()
    bindings = {"renamed": entry}
    assert bindings["renamed"] is entry
    assert isinstance(bindings["renamed"], BindingEntryV1)
    assert bindings["renamed"].state is live_state


def test_loop_projection_carries_exact_completed_faces_inside_runtime_entry():
    assignment, live_state, _entry_value = _entry()
    target_cid = cid_of_json({"loop": assignment.fragment.seal().to_dict()})
    first_guard = cid_of_json({"guard": "break"})
    second_guard = cid_of_json({"guard": "exhaustion"})
    projection = LoopProjectedBinding(
        target_cid=target_cid,
        completed_faces=(
            LoopProjectedCompletedFace(
                target_cid, "BreakExit", first_guard, live_state
            ),
            LoopProjectedCompletedFace(
                target_cid, "NormalExhaustion", second_guard, live_state
            ),
        ),
    )
    factory = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": assignment.fragment.seal().to_dict()})
    )

    entry = factory.mint_entry(
        binding_site=assignment.targets[0].fragment,
        projection_path=("loop-post", 0),
        state=projection,
    )

    assert isinstance(entry, BindingEntryV1)
    assert entry.state is projection
    assert tuple(face.guard_formula_cid for face in projection.completed_faces) == (
        first_guard,
        second_guard,
    )
    assert tuple(face.state for face in projection.completed_faces) == (
        live_state,
        live_state,
    )
    with pytest.raises(BindingStateWireGap, match="loop projected binding"):
        entry.wire()


def test_loop_projection_rejects_lying_target_and_cid_as_runtime_value():
    _assignment, live_state, _entry_value = _entry()
    target_cid = cid_of_json({"loop": "truthful"})
    other_target_cid = cid_of_json({"loop": "lying"})
    guard_cid = cid_of_json({"guard": True})

    with pytest.raises(BindingStateWireGap, match="target mismatch"):
        LoopProjectedBinding(
            target_cid=target_cid,
            completed_faces=(
                LoopProjectedCompletedFace(
                    other_target_cid, "BreakExit", guard_cid, live_state
                ),
            ),
        )
    with pytest.raises(BindingStateWireGap, match="runtime binding state"):
        LoopProjectedCompletedFace(
            target_cid,
            "BreakExit",
            guard_cid,
            cid_of_json({"fabricated": "value"}),
        )


def test_constructed_value_v2_seals_float_and_bytes():
    # Float and bytes literal testimony must enter the closed canonical wire.
    from sugar_source_tree.binding_state import (
        ConstructedValueCategoryGap,
        _cv2_leaf,
    )

    # Float -> the ONE canonical fixed-point decimal string the system uses
    # (ir.real_lit), tagged so a float never collides with the str "1.5".
    assert _cv2_leaf(1.5) == {"float": "1.5"}
    assert _cv2_leaf(0.0) == {"float": "0.0"}
    assert _cv2_leaf(-2.25) == {"float": "-2.25"}
    assert _cv2_leaf(1e-05) == {"float": "0.00001"}
    # Bytes -> hex, matching bytes_value / sequence_repetition.
    assert _cv2_leaf(b"\xde\xad\xbe\xef") == {"bytes": "deadbeef"}
    # A tagged float can never be read as the string that spells it.
    assert _cv2_leaf(1.5) != _cv2_leaf("1.5")

    # Both must be canonical-JSON admissible and deterministic.
    for value in (1.5, 0.0, b"\x00\xff"):
        encoded = _cv2_leaf(value)
        assert cid_of_json({"v": encoded}) == cid_of_json({"v": encoded})

    # Bad twin: a value with no canonical spelling stays LOUD, never silently
    # collapses to a fabricated testimony, and never falls back to reflection.
    from sugar_source_tree.binding_state import constructed_value_cid_v2

    from sugar_source_tree.binding_state import _NOT_A_LEAF

    assert _cv2_leaf(1 + 2j) is _NOT_A_LEAF
    with pytest.raises(ConstructedValueCategoryGap, match="unclassified"):
        constructed_value_cid_v2(1 + 2j)
