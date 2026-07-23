from __future__ import annotations

import copy
import importlib.util
import tempfile
from pathlib import Path

import pytest

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.loop_construction import (
    LoopConstructionV1,
    LoopWireError,
    decode_loop_construction_v1,
)
from sugar_source_tree.binding_provenance import BindingCoordinateV1
from sugar_source_tree.binding_state import (
    BindingEntryV1,
    BindingStateWireGap,
    LoopProjectedBinding,
    LoopProjectedCompletedFace,
)
from sugar_source_tree.loop_recurrence import project_loop_post_binding
from sugar_source_tree.nodes import _construct_binding_projection
from sugar_source_tree.binding_state import RuntimeBindingEntryFactoryV1
from sugar_source_tree.tree import SourceFile


def _entry(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    function = next(SourceFile(path_source(path)).functions())
    assignment = next(node for node in function.walk() if node.kind == "Assign")
    live_state = assignment.value
    factory = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": function.fragment.seal().to_dict()})
    )
    entry = factory.mint_entry(
        binding_site=assignment.targets[0].fragment,
        projection_path=("targets", 0),
        state=live_state,
    )
    return assignment, live_state, entry


def _sample_construction():
    path = (
        Path(__file__).parents[2]
        / "sugar-lift-py-tests"
        / "tests"
        / "test_loop_construction_wire.py"
    )
    spec = importlib.util.spec_from_file_location("loop_wire_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return decode_loop_construction_v1(module._sample_graph())


def _sample_coordinate(construction):
    state = next(
        record
        for record in construction.wire_graph()["records"]
        if record.get("kind") == "binding-state" and record["entries"]
    )
    return BindingCoordinateV1.decode(state["entries"][0]["coordinate"])


def test_break_and_exhaustion_faces_project_exact_runtime_states_by_coordinate():
    _assignment, break_state, break_entry = _entry(
        "def arbitrary():\n    carried = 1\n"
    )
    _assignment2, exhaustion_state, exhaustion_entry = _entry(
        "def arbitrary():\n    carried = 2\n"
    )
    construction = _sample_construction()
    coordinate = _sample_coordinate(construction)
    break_entry = BindingEntryV1(coordinate, break_state, None)
    exhaustion_entry = BindingEntryV1(coordinate, exhaustion_state, None)
    graph = construction.wire_graph()
    state_cids = {
        record["stateCid"]
        for record in graph["records"]
        if record.get("kind") == "binding-state"
    }
    runtime_states = {
        state_cid: (
            break_entry
            if state_cid
            == next(
                face.state_cid
                for face in construction.completed_faces
                if face.completion_kind == "BreakExit"
            )
            else exhaustion_entry,
        )
        for state_cid in state_cids
    }

    projected = project_loop_post_binding(
        construction=construction,
        binding_coordinate=coordinate,
        runtime_states=runtime_states,
    )

    assert isinstance(projected, LoopProjectedBinding)
    assert projected.target_cid == construction.target.target_cid
    assert [face.completion_kind for face in projected.completed_faces] == [
        "BreakExit",
        "BodyFallthrough",
        "NormalExhaustion",
    ]
    assert projected.completed_faces[0].state is break_state
    assert projected.completed_faces[1].state is exhaustion_state
    assert projected.completed_faces[2].state is exhaustion_state


def test_projection_is_typed_loud_for_missing_state_or_coordinate():
    _assignment, _state, entry = _entry("def arbitrary():\n    carried = 1\n")
    construction = _sample_construction()
    coordinate = _sample_coordinate(construction)
    state_cid = construction.completed_faces[0].state_cid

    with pytest.raises(BindingStateWireGap, match="runtime state"):
        project_loop_post_binding(
            construction=construction,
            binding_coordinate=coordinate,
            runtime_states={},
        )
    with pytest.raises(BindingStateWireGap, match="binding coordinate"):
        project_loop_post_binding(
            construction=construction,
            binding_coordinate=coordinate,
            runtime_states={state_cid: ()},
        )


def test_projection_redecodes_and_rejects_a_spliced_public_dataclass():
    construction = _sample_construction()
    graph = copy.deepcopy(construction.wire_graph())
    face = next(
        record for record in graph["records"] if record.get("kind") == "loop-completed-face"
    )
    face["completionKind"] = "NormalExhaustion"
    spliced = LoopConstructionV1(
        construction.target,
        construction.pre_state,
        construction.operation,
        construction.completed_faces,
        construction.loop_construction_cid,
        graph,
    )

    with pytest.raises(LoopWireError, match="completedFaceCid mismatch"):
        project_loop_post_binding(
            construction=spliced,
            binding_coordinate=_sample_coordinate(construction),
            runtime_states={},
        )


def test_downstream_binding_read_stays_loud_without_exact_guard_formulas():
    _assignment, live_state, _entry_value = _entry(
        "def arbitrary():\n    carried = 1\n"
    )
    target_cid = cid_of_json({"target": "loop"})
    projection = LoopProjectedBinding(
        target_cid,
        (
            LoopProjectedCompletedFace(
                target_cid,
                "BreakExit",
                cid_of_json({"guard": "break"}),
                live_state,
            ),
            LoopProjectedCompletedFace(
                target_cid,
                "NormalExhaustion",
                cid_of_json({"guard": "exhaustion"}),
                live_state,
            ),
        ),
    )

    with pytest.raises(BindingStateWireGap, match="exact guard formula"):
        _construct_binding_projection(projection)
