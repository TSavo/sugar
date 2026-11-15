"""Exact post-binding denominator for a loop that can ``break``.

A Python loop statement completes by exactly two routes here: ``break`` and
normal exhaustion.  ``BodyFallthrough`` is the latch input -- the body running
to its end and going round again -- so no statement after the loop sees its
state, and the post-binding projection carries exactly the two exit routes,
each under its own guard.

The loop was CPython ``enum.py:304``.  The function that holds it reads the
module's ``Flag`` where the module body does not decide it, and is refused
by that name (``_bound_module_references``) before its loop is reached: a true
refusal, never traded for the loop.  The loop is now the shape it had --
a name carried across a ``for`` that can ``break``, read after the loop --
in a file of its own (``test_loop_exit_partition_carrier.FIXTURE``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_source_tree.binding_state import BindingStateWireGap

# A name carried across a ``for`` loop that can ``break``, then read after
# the loop: the read is where the two exit faces become two completed arms.
FIXTURE = """\
def compute(columns, seed, sink):
    indexer = seed
    for column in columns:
        indexer = indexer.append(column)
        if column.done:
            break
    sink.result = indexer.finish()
    return sink
"""


def _loop_projection_calls(monkeypatch, tmp_path: Path):
    """Run the fixture's function and retain its exact projection inputs."""
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree import loop_recurrence
    from sugar_source_tree.tree import SourceFile

    path = tmp_path / "fixture.py"
    path.write_text(FIXTURE)
    calls = []
    original = loop_recurrence.project_loop_post_binding

    def observe(**kwargs):
        calls.append((kwargs, None))
        projected = original(**kwargs)
        calls[-1] = (kwargs, projected)
        return projected

    monkeypatch.setattr(loop_recurrence, "project_loop_post_binding", observe)
    for function in SourceFile(
        path_source(str(path)),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    ).functions():
        function.sugar().desugar(None)
    assert calls
    return calls, original


def test_post_binding_carries_exactly_the_two_exit_routes(
    monkeypatch, tmp_path: Path
) -> None:
    calls, _original = _loop_projection_calls(monkeypatch, tmp_path)
    for kwargs, projected in calls:
        assert projected is not None
        construction = kwargs["construction"]
        graph = construction.wire_graph()
        post_records = tuple(
            record
            for record in graph["records"]
            if record.get("kind") == "loop-post-binding"
            and record["bindingCoordinateCid"] == kwargs["binding_coordinate"].cid
        )
        assert {record["exitPartitionArity"] for record in post_records} == {2}
        assert len(projected.completed_faces) == len(post_records) == 2
        assert {face.completion_kind for face in projected.completed_faces} == {
            "BreakExit",
            "NormalExhaustion",
        }
        assert len({face.guard_formula_cid for face in projected.completed_faces}) == 2
        root = graph["root"]
        assert len(root["breakExitObligationCids"]) == 1
        assert root["exhaustionExitObligationCid"]


@pytest.mark.parametrize(
    "axis", ("missing", "duplicate", "foreign_coordinate", "guard_collapsed")
)
def test_post_binding_route_lies_remain_typed_loud(
    monkeypatch, tmp_path: Path, axis
) -> None:
    calls, original = _loop_projection_calls(monkeypatch, tmp_path)
    kwargs = dict(calls[0][0])
    # The lie is told about a state the projection reads: a completed exit
    # route's (``projectedStateCid``).  ``runtime_states`` also holds the
    # loop's entry state (``live_loop_construction``: the pre-state is its
    # first key), which no exit route projects, so a lie about it is no lie
    # about the post-binding partition.
    state_cid = next(
        record["projectedStateCid"]
        for record in kwargs["construction"].wire_graph()["records"]
        if record.get("kind") == "loop-post-binding"
        and record["bindingCoordinateCid"] == kwargs["binding_coordinate"].cid
    )
    if axis == "missing":
        states = dict(kwargs["runtime_states"])
        states.pop(state_cid)
        kwargs["runtime_states"] = states
    elif axis == "duplicate":
        states = dict(kwargs["runtime_states"])
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
