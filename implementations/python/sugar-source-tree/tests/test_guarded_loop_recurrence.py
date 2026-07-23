from __future__ import annotations

import tempfile
from types import SimpleNamespace

import pytest

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.loop_construction import LoopConstructionV1
from sugar_source_tree.binding_state import (
    BindingStateWireGap,
    LoopProjectedBinding,
    LoopProjectedCompletedFace,
)
from sugar_source_tree.loop_recurrence import project_loop_post_binding
from sugar_source_tree.nodes import _construct_binding_projection
from sugar_source_tree.binding_state import RuntimeBindingEntryFactoryV1
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.sugar.binding_projection import LoopCompletedFacesProjection


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


def _construction(target_cid, faces, state_cids):
    records = [
        {
            "kind": "loop-completed-face",
            "completedFaceCid": face.cid,
            "targetCid": face.target_cid,
            "completionKind": face.completion_kind,
            "guardFormulaCid": face.guard_formula_cid,
            "stateCid": state_cid,
        }
        for face, state_cid in zip(faces, state_cids, strict=True)
    ]
    return LoopConstructionV1(
        target=SimpleNamespace(target_cid=target_cid),
        pre_state=SimpleNamespace(state_cid=cid_of_json({"state": "pre"})),
        operation=SimpleNamespace(kind="for-operation"),
        completed_faces=tuple(faces),
        loop_construction_cid=cid_of_json({"loop": target_cid}),
        _graph={"root": {}, "records": records},
    )


def test_break_and_exhaustion_faces_project_exact_runtime_states_by_coordinate():
    _assignment, break_state, break_entry = _entry(
        "def arbitrary():\n    carried = 1\n"
    )
    _assignment2, exhaustion_state, exhaustion_entry = _entry(
        "def arbitrary():\n    carried = 2\n"
    )
    coordinate = break_entry.coordinate
    exhaustion_entry = type(exhaustion_entry)(
        coordinate, exhaustion_entry.state, exhaustion_entry.sealed_state
    )
    target_cid = cid_of_json({"target": "loop"})
    break_state_cid = cid_of_json({"state": "break"})
    exhaustion_state_cid = cid_of_json({"state": "exhaustion"})
    faces = (
        SimpleNamespace(
            cid=cid_of_json({"face": "break"}),
            target_cid=target_cid,
            completion_kind="BreakExit",
            guard_formula_cid=cid_of_json({"guard": "break"}),
        ),
        SimpleNamespace(
            cid=cid_of_json({"face": "exhaustion"}),
            target_cid=target_cid,
            completion_kind="NormalExhaustion",
            guard_formula_cid=cid_of_json({"guard": "exhaustion"}),
        ),
    )
    construction = _construction(
        target_cid, faces, (break_state_cid, exhaustion_state_cid)
    )

    projected = project_loop_post_binding(
        construction=construction,
        binding_coordinate=coordinate,
        runtime_states={
            break_state_cid: (break_entry,),
            exhaustion_state_cid: (exhaustion_entry,),
        },
    )

    assert isinstance(projected, LoopProjectedBinding)
    assert projected.target_cid == target_cid
    assert [face.completion_kind for face in projected.completed_faces] == [
        "BreakExit",
        "NormalExhaustion",
    ]
    assert projected.completed_faces[0].state is break_state
    assert projected.completed_faces[1].state is exhaustion_state


def test_projection_is_typed_loud_for_missing_state_or_coordinate():
    _assignment, _state, entry = _entry("def arbitrary():\n    carried = 1\n")
    target_cid = cid_of_json({"target": "loop"})
    state_cid = cid_of_json({"state": "completed"})
    face = SimpleNamespace(
        cid=cid_of_json({"face": "completed"}),
        target_cid=target_cid,
        completion_kind="NormalExhaustion",
        guard_formula_cid=cid_of_json({"guard": "completed"}),
    )
    construction = _construction(target_cid, (face,), (state_cid,))

    with pytest.raises(BindingStateWireGap, match="runtime state"):
        project_loop_post_binding(
            construction=construction,
            binding_coordinate=entry.coordinate,
            runtime_states={},
        )
    with pytest.raises(BindingStateWireGap, match="binding coordinate"):
        project_loop_post_binding(
            construction=construction,
            binding_coordinate=entry.coordinate,
            runtime_states={state_cid: ()},
        )


def test_projection_rejects_a_lying_face_target():
    _assignment, _state, entry = _entry("def arbitrary():\n    carried = 1\n")
    target_cid = cid_of_json({"target": "truthful"})
    state_cid = cid_of_json({"state": "completed"})
    face = SimpleNamespace(
        cid=cid_of_json({"face": "completed"}),
        target_cid=cid_of_json({"target": "lying"}),
        completion_kind="BreakExit",
        guard_formula_cid=cid_of_json({"guard": "break"}),
    )
    construction = _construction(target_cid, (face,), (state_cid,))

    with pytest.raises(BindingStateWireGap, match="target mismatch"):
        project_loop_post_binding(
            construction=construction,
            binding_coordinate=entry.coordinate,
            runtime_states={state_cid: (entry,)},
        )


def test_downstream_binding_read_consumes_every_guarded_completed_face():
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

    consumed = _construct_binding_projection(projection)

    assert isinstance(consumed, LoopCompletedFacesProjection)
    assert consumed.target_cid == target_cid
    assert [face.completion_kind for face in consumed.completed_faces] == [
        "BreakExit",
        "NormalExhaustion",
    ]
    assert [face.guard_formula_cid for face in consumed.completed_faces] == [
        projection.completed_faces[0].guard_formula_cid,
        projection.completed_faces[1].guard_formula_cid,
    ]
