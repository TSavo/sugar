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
    ]
    assert projected.completed_faces[0].state is break_state


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


def test_seal_runtime_state_seals_guarded_join_and_stays_loud_on_projected():
    # A branch-joined GuardedBinding carried into a loop pre-state must seal
    # through the ONE recursive projection -- not stay loud as a Node-only
    # special case did (the pandas frame/indexing/blocks loop crashes).
    from sugar_source_tree.binding_provenance import (
        BoundBindingStateV1,
        GuardedBindingStateV1,
        _state_wire,
    )
    from sugar_source_tree.binding_state import GuardedBinding, branch_result_slot
    from sugar_source_tree.live_loop_construction import (
        _formula_cid,
        _seal_runtime_state,
    )
    from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard

    _a, node_true, _e1 = _entry("def f():\n    y = 1\n")
    _b, node_false, _e2 = _entry("def f():\n    y = 2\n")
    _c, test_node, _e3 = _entry("def f():\n    t = 3\n")
    slot = branch_result_slot(test_node)

    sealed = _seal_runtime_state(GuardedBinding(slot, node_true, node_false))
    assert isinstance(sealed, GuardedBindingStateV1)
    # each arm addresses by the content CID of its OWN sealed state (recursion)
    assert sealed.when_true_state_cid == cid_of_json(
        _state_wire(_seal_runtime_state(node_true))
    )
    assert sealed.when_false_state_cid == cid_of_json(
        _state_wire(_seal_runtime_state(node_false))
    )
    # the guard is the SAME branch-result guard the loop control faces use
    assert sealed.guard_formula_cid == _formula_cid(
        branch_result_guard(slot, slot)
    )
    # a constructed Node arm seals to a bound value, not a guard
    assert isinstance(_seal_runtime_state(node_true), BoundBindingStateV1)

    # A SINGLE-face loop projection is TOTAL (a no-break loop exits only by
    # NormalExhaustion), so it seals to that one face's state unconditionally.
    target_cid = cid_of_json({"target": "loop"})
    single = LoopProjectedBinding(
        target_cid,
        (
            LoopProjectedCompletedFace(
                target_cid, "NormalExhaustion", cid_of_json({"g": "x"}), node_true
            ),
        ),
    )
    assert _seal_runtime_state(single) == _seal_runtime_state(node_true)

    # Bad twin: a MULTI-face projection (a loop that can break) is a genuine
    # multi-way completion join whose folding is unbuilt -- it stays LOUD,
    # never silently folds to a wrong fallthrough value.
    multi = LoopProjectedBinding(
        target_cid,
        (
            LoopProjectedCompletedFace(
                target_cid, "BreakExit", cid_of_json({"g": "b"}), node_true
            ),
            LoopProjectedCompletedFace(
                target_cid, "NormalExhaustion", cid_of_json({"g": "x"}), node_false
            ),
        ),
    )
    with pytest.raises(BindingStateWireGap, match="multi-face"):
        _seal_runtime_state(multi)


def test_conserve_unique_records_collapses_identical_keeps_distinct():
    # Loop-graph assembly can re-emit a byte-identical record; the decoder keys
    # records by CID and requires each once. Conservation collapses exact
    # duplicates (first order preserved) but never a genuinely distinct record.
    from sugar_source_tree.live_loop_construction import _conserve_unique_records

    a = {"kind": "loop-body-transform", "bodyTransformCid": "cid-a"}
    b = {"kind": "loop-latch-obligation", "latchObligationCid": "cid-b"}
    c = {"kind": "loop-body-transform", "bodyTransformCid": "cid-c"}

    # identical re-emissions of a and b collapse to one each, in first order
    assert _conserve_unique_records([a, b, dict(a), dict(b)]) == [a, b]
    # distinct records (different content) are all retained
    assert _conserve_unique_records([a, c, b]) == [a, c, b]


def test_binding_state_read_node_reads_through_single_face_projection():
    # A single-face LoopProjectedBinding is the TOTAL post-value; the read path
    # must read straight through it (regression: pandas core/util/hashing).
    # A multi-face join stays loud rather than silently pick one arm.
    from sugar_source_tree.binding_state import binding_state_read_node

    _a, node, _e = _entry("def f():\n    y = 1\n")
    target_cid = cid_of_json({"target": "loop"})
    single = LoopProjectedBinding(
        target_cid,
        (
            LoopProjectedCompletedFace(
                target_cid, "NormalExhaustion", cid_of_json({"g": "x"}), node
            ),
        ),
    )
    sentinel = object()
    assert binding_state_read_node(single, make_read=lambda s: sentinel) is node

    multi = LoopProjectedBinding(
        target_cid,
        (
            LoopProjectedCompletedFace(
                target_cid, "BreakExit", cid_of_json({"g": "b"}), node
            ),
            LoopProjectedCompletedFace(
                target_cid, "NormalExhaustion", cid_of_json({"g": "x"}), node
            ),
        ),
    )
    with pytest.raises(TypeError):
        binding_state_read_node(multi, make_read=lambda s: sentinel)
