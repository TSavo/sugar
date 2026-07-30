"""Exact post-binding denominator for CPython ``enum.py:304``.

The loop has three completed-state routes (break, internal latch fallthrough,
normal exhaustion) but only two outward exits (break and exhaustion).  A
post-binding projection conserves all three states; it must not borrow the
two-route outward denominator.
"""

from __future__ import annotations

import pytest

from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph
from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_source_tree.binding_state import BindingStateWireGap
from sugar_source_tree.nodes import For, FunctionDef
from sugar_source_tree.tree import SourceFile


def _enum_loop_projection_calls(monkeypatch):
    """Run the ordinary enum function and retain its exact projection inputs."""
    from sugar_source_tree import loop_recurrence

    graph = DependencyArtifactGraph.authenticate_stdlib_module("enum")
    module = graph.modules["enum"]
    source = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    loop = next(
        node
        for node in source.nodes()
        if isinstance(node, For) and node.line_col_span().start_line == 304
    )
    owner = min(
        (
            node
            for node in source.nodes()
            if isinstance(node, FunctionDef)
            and node.line_col_span().start_line < 304
            and node.line_col_span().end_line >= 304
        ),
        key=lambda node: node.line_col_span().end_line
        - node.line_col_span().start_line,
    )
    calls = []
    original = loop_recurrence.project_loop_post_binding

    def observe(**kwargs):
        calls.append((kwargs, None))
        projected = original(**kwargs)
        calls[-1] = (kwargs, projected)
        return projected

    monkeypatch.setattr(loop_recurrence, "project_loop_post_binding", observe)
    try:
        owner.sugar().desugar(None)
    except BindingStateWireGap:
        # The instrument's truthful tooth reports the exact current red.  The
        # captured owner inputs remain usable by the independent lying twins.
        pass
    assert calls
    return loop, calls, original


def test_enum_post_binding_preserves_three_states_and_two_outward_routes(
    monkeypatch,
) -> None:
    loop, calls, _original = _enum_loop_projection_calls(monkeypatch)
    del loop
    for kwargs, projected in calls:
        assert projected is not None
        construction = kwargs["construction"]
        graph = construction.wire_graph()
        post_records = tuple(
            record
            for record in graph["records"]
            if record.get("kind") == "loop-post-binding"
            and record["bindingCoordinateCid"]
            == kwargs["binding_coordinate"].cid
        )
        assert {record["exitPartitionArity"] for record in post_records} == {3}
        assert len(projected.completed_faces) == len(post_records) == 3
        assert {
            face.completion_kind for face in projected.completed_faces
        } == {"BreakExit", "BodyFallthrough", "NormalExhaustion"}
        assert len(
            {face.guard_formula_cid for face in projected.completed_faces}
        ) == 3
        root = graph["root"]
        assert len(root["breakExitObligationCids"]) == 1
        assert root["exhaustionExitObligationCid"]


@pytest.mark.parametrize(
    "axis", ("missing", "duplicate", "foreign_coordinate", "guard_collapsed")
)
def test_enum_post_binding_route_lies_remain_typed_loud(monkeypatch, axis) -> None:
    _loop, calls, original = _enum_loop_projection_calls(monkeypatch)
    kwargs = dict(calls[0][0])
    if axis == "missing":
        states = dict(kwargs["runtime_states"])
        states.pop(next(iter(states)))
        kwargs["runtime_states"] = states
    elif axis == "duplicate":
        states = dict(kwargs["runtime_states"])
        state_cid = next(iter(states))
        states[state_cid] = (*states[state_cid], *states[state_cid])
        kwargs["runtime_states"] = states
    elif axis == "foreign_coordinate":
        coordinate = kwargs["binding_coordinate"]
        kwargs["binding_coordinate"] = coordinate.project("foreign")
    else:
        guards = dict(kwargs["live_guards"])
        one_guard = next(iter(guards.values()))
        kwargs["live_guards"] = dict.fromkeys(guards, one_guard)

    with pytest.raises(BindingStateWireGap):
        original(**kwargs)
