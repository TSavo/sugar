"""Production laws for temporal recurrence of source-constructed ``while``."""

from __future__ import annotations

from pathlib import Path

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.nodes import While
from sugar_source_tree.tree import SourceFile


def _function(tmp_path: Path, source: str):
    path = tmp_path / "while_temporal_recurrence.py"
    path.write_text(source, encoding="utf-8")
    return next(SourceFile(path_source(path)).functions())


def _record(graph, kind: str):
    return next(record for record in graph["records"] if record["kind"] == kind)


def test_body_state_is_the_next_condition_input_not_the_stale_initial_state(
    tmp_path: Path,
):
    function = _function(
        tmp_path,
        "def helper(limit):\n"
        "    current = 0\n"
        "    while current < limit:\n"
        "        current = current + 1\n"
        "    return current\n",
    )
    while_node = next(node for node in function.walk() if isinstance(node, While))
    loop = next(
        statement
        for statement in function.sugar().statements
        if type(statement).__name__ == "LoopRecurrenceSugar"
    )
    graph = loop.construction.wire_graph()
    test_transform = _record(graph, "loop-test-transform")
    latch = _record(graph, "loop-latch-obligation")

    assert test_transform["testValueConstructionCid"] == (
        while_node.test.fragment.seal().cid
    )
    assert latch["successorTransformCid"] == test_transform["testTransformCid"]
    assert latch["inputStateCid"] != graph["root"]["preStateCid"]
    assert test_transform["inputStateCid"] == latch["inputStateCid"], (
        "the reached next condition must consume the body-completed state; "
        "reusing preStateCid is the stale-initial-state lying twin"
    )
