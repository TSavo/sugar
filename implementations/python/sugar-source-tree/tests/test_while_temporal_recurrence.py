"""Production laws for temporal recurrence of source-constructed ``while``."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from sugar_lift_py_tests.loop_construction import (
    LoopWireError,
    decode_loop_construction_v1,
    seal_loop_record,
)
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
    test_transforms = tuple(
        record for record in graph["records"] if record["kind"] == "loop-test-transform"
    )
    operation = graph["root"]["operation"]
    latch = _record(graph, "loop-latch-obligation")
    initial = next(
        transform
        for transform in test_transforms
        if transform["testTransformCid"] == operation["testTransformCid"]
    )
    recurrence = next(
        transform
        for transform in test_transforms
        if transform["testTransformCid"] == latch["successorTransformCid"]
    )

    assert len(test_transforms) == 2
    assert initial["testValueConstructionCid"] == (
        while_node.test.fragment.seal().cid
    )
    assert recurrence["testValueConstructionCid"] == initial["testValueConstructionCid"]
    assert initial["inputStateCid"] == graph["root"]["preStateCid"]
    assert latch["inputStateCid"] != graph["root"]["preStateCid"]
    assert recurrence["inputStateCid"] == latch["inputStateCid"], (
        "the reached next condition must consume the body-completed state; "
        "reusing preStateCid is the stale-initial-state lying twin"
    )


def test_swapping_only_recurrence_test_back_to_pre_state_is_refused(tmp_path: Path):
    """Lying coordinate twin: a sealed stale-state transform is still invalid."""
    function = _function(
        tmp_path,
        "def renamed(bound):\n"
        "    value = 0\n"
        "    while value < bound:\n"
        "        value = value + 1\n"
        "    return value\n",
    )
    loop = next(
        statement
        for statement in function.sugar().statements
        if type(statement).__name__ == "LoopRecurrenceSugar"
    )
    graph = loop.construction.wire_graph()
    tampered = deepcopy(graph)
    latch = _record(tampered, "loop-latch-obligation")
    recurrence = next(
        record
        for record in tampered["records"]
        if record.get("testTransformCid") == latch["successorTransformCid"]
    )

    old_transform_cid = recurrence["testTransformCid"]
    transform_preimage = {
        key: value for key, value in recurrence.items() if key != "testTransformCid"
    }
    transform_preimage["inputStateCid"] = tampered["root"]["preStateCid"]
    replacement = seal_loop_record(transform_preimage, "testTransformCid")
    recurrence.clear()
    recurrence.update(replacement)

    old_latch_cid = latch["latchObligationCid"]
    latch_preimage = {
        key: value for key, value in latch.items() if key != "latchObligationCid"
    }
    latch_preimage["successorTransformCid"] = replacement["testTransformCid"]
    replacement_latch = seal_loop_record(latch_preimage, "latchObligationCid")
    latch.clear()
    latch.update(replacement_latch)
    tampered["root"]["latchObligationCids"] = [
        replacement_latch["latchObligationCid"]
        if cid == old_latch_cid
        else cid
        for cid in tampered["root"]["latchObligationCids"]
    ]
    assert old_transform_cid != replacement["testTransformCid"]
    root_preimage = {
        key: value
        for key, value in tampered["root"].items()
        if key != "loopConstructionCid"
    }
    tampered["root"] = seal_loop_record(root_preimage, "loopConstructionCid")

    with pytest.raises(LoopWireError, match="duplicate loop graph CID"):
        decode_loop_construction_v1(tampered)
