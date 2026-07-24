from __future__ import annotations

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.effect import LoopControlEffect
from sugar_lift_py_tests.outcome import Halted
from sugar_source_tree.tree import SourceFile
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.binding_provenance import SubstitutionTraceV1


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    return next(SourceFile(path_source(path)).functions())


def test_break_and_continue_emit_owned_halted_exitset_faces():
    function = _function(
        "def arbitrary(xs):\n"
        "    for item in xs:\n"
        "        if item:\n"
        "            continue\n"
        "        break\n"
    )
    controls = [node for node in function.walk() if node.kind in {"Break", "Continue"}]
    exits = [node.sugar().desugar().exits[0] for node in controls]
    assert all(isinstance(exit_, Halted) for exit_ in exits)
    assert all(isinstance(exit_.effect, LoopControlEffect) for exit_ in exits)
    assert {exit_.effect.action for exit_ in exits} == {"break", "continue"}
    assert len({exit_.effect.target_cid for exit_ in exits}) == 1


def test_function_construction_carries_authenticated_pre_post_binding_trace():
    function = _function(
        "def arbitrary():\n"
        "    renamed = 1\n"
        "    for item in (2,):\n"
        "        renamed = renamed + item\n"
        "    return renamed\n"
    )
    trace = function.sugar().substitution_trace
    assert isinstance(trace, SubstitutionTraceV1)
    assert len(trace.records) == 4
    assert trace.records[0].pre_entries == ()
    assert trace.records[0].post_entries[0].coordinate.cid
    testified_coordinates = {
        entry.coordinate.cid
        for record in trace.records
        for entry in (*record.pre_entries, *record.post_entries)
    }
    assert len(testified_coordinates) >= 3
    assert SubstitutionTraceV1.decode(trace.wire()).wire() == trace.wire()


def test_nested_controls_target_the_nearest_structural_loop():
    function = _function(
        "def arbitrary(xss):\n"
        "    for xs in xss:\n"
        "        for item in xs:\n"
        "            break\n"
        "        continue\n"
    )
    controls = [node for node in function.walk() if node.kind in {"Break", "Continue"}]
    targets = {node.kind: node.sugar().target_cid for node in controls}
    assert targets["Break"] != targets["Continue"]


def test_loop_control_coordinate_has_no_identifier_name_gate():
    left = _function("def left(values):\n    for renamed in values:\n        break\n")
    right = _function("def right(values):\n    for other in values:\n        break\n")
    left_sugar = next(node for node in left.walk() if node.kind == "Break").sugar()
    right_sugar = next(node for node in right.walk() if node.kind == "Break").sugar()
    assert left_sugar.target_cid != right_sugar.target_cid


def test_bounded_break_unrolls_only_the_visited_prefix_and_skips_else():
    function = _function(
        "def arbitrary():\n"
        "    for renamed in (0, 1, 2, 3):\n"
        "        if renamed == 2:\n"
        "            break\n"
        "        seen = renamed\n"
        "    else:\n"
        "        seen = 99\n"
        "    return seen\n"
    ).substitute({})
    assert not any(node.kind in {"For", "Break"} for node in function.walk())
    returned = next(node for node in function.walk() if node.kind == "Return")
    assert returned.value.kind == "Constant"
    assert returned.value.value == 1


def test_bounded_continue_routes_to_next_iteration_and_omits_tail():
    function = _function(
        "def arbitrary():\n"
        "    kept = -1\n"
        "    for renamed in (0, 1, 2):\n"
        "        if renamed == 1:\n"
        "            continue\n"
        "        kept = renamed\n"
        "    return kept\n"
    ).substitute({})
    assert not any(node.kind in {"For", "Continue"} for node in function.walk())
    returned = next(node for node in function.walk() if node.kind == "Return")
    assert returned.value.kind == "Constant"
    assert returned.value.value == 2


def test_bounded_exhaustion_runs_else_and_exports_final_target_binding():
    function = _function(
        "def arbitrary():\n"
        "    marker = -1\n"
        "    for renamed in (4, 5):\n"
        "        marker = renamed\n"
        "    else:\n"
        "        marker = renamed + 1\n"
        "    return marker\n"
    ).substitute({})
    returned = next(node for node in function.walk() if node.kind == "Return")
    assert returned.value.kind == "BinOp"
    assert returned.value.left.value == 5
    assert returned.value.right.value == 1


def test_bounded_while_break_skips_else_with_exact_post_state():
    source = (
        "def arbitrary():\n"
        "    item = 0\n"
        "    while item < 4:\n"
        "        item = item + 1\n"
        "        if item == 2:\n"
        "            break\n"
        "    else:\n"
        "        item = 99\n"
        "    return item\n"
    )
    substituted = _function(source).substitute({})
    assert not any(node.kind in {"While", "Break"} for node in substituted.walk())
    post = _function(source).sugar().desugar().value.post()
    assert post.args[1].value == 2


def test_bounded_while_continue_routes_to_test_backedge():
    post = (
        _function(
            "def arbitrary():\n"
            "    item = 0\n"
            "    kept = 0\n"
            "    while item < 3:\n"
            "        item = item + 1\n"
            "        if item == 2:\n"
            "            continue\n"
            "        kept = kept + item\n"
            "    return kept\n"
        )
        .sugar()
        .desugar()
        .value.post()
    )
    assert post.args[1].value == 4


def test_symbolic_break_never_fabricates_a_whole_iterable_universal():
    function = _function(
        "def arbitrary(values, stop):\n"
        "    for renamed in values:\n"
        "        if renamed == stop:\n"
        "            break\n"
        "        assert renamed != stop\n"
    )
    constructed = function.sugar()
    assert type(constructed.statements[0]).__name__ == "LoopRecurrenceSugar"
    assert "ForUniversalSugar" not in repr(constructed)


def test_nested_break_is_consumed_only_by_the_inner_bounded_loop():
    post = (
        _function(
            "def arbitrary():\n"
            "    count = 0\n"
            "    for outer in (0, 1):\n"
            "        for inner in (0, 1):\n"
            "            break\n"
            "        count = count + 1\n"
            "    return count\n"
        )
        .sugar()
        .desugar()
        .value.post()
    )
    assert post.args[1].value == 2


def test_nested_continue_is_consumed_only_by_the_inner_bounded_loop():
    post = (
        _function(
            "def arbitrary():\n"
            "    count = 0\n"
            "    for outer in (0, 1):\n"
            "        for inner in (0, 1):\n"
            "            if inner == 0:\n"
            "                continue\n"
            "            count = count + 1\n"
            "        count = count + 10\n"
            "    return count\n"
        )
        .sugar()
        .desugar()
        .value.post()
    )
    assert post.args[1].value == 22


def test_loop_else_preserves_a_carried_name_it_never_rebinds():
    # A name carried through the loop (rebound in the body) that the else clause
    # does NOT touch keeps its loop-exhaustion value. The else-net holds only
    # names the else REBOUND, so it must fall back to the exhaustion state, not
    # KeyError (regression: pandas io/html, io/excel/_xlsxwriter, _version).
    post = (
        _function(
            "def arbitrary():\n"
            "    total = 0\n"
            "    for i in (1, 2):\n"
            "        total = total + i\n"
            "    else:\n"
            "        seen = True\n"
            "    return total\n"
        )
        .sugar()
        .desugar()
        .value.post()
    )
    assert post.args[1].value == 3
