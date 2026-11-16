"""``break`` and ``continue`` are halts their owning loop consumes. A loop
over members in hand runs item by item in the reduction (#7757 new 6,
#8957): no rewrite unrolls it, so the bounded loops below are read through
the function's reduced post, never through a rewritten tree.

Each file is opened through the one construction door under a workspace
root, as the lift opens it: the iteration's own ``StopIteration`` cites a
workspace-relative locus."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sugar_lift_py_tests.effect import LoopControlEffect
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Halted
from sugar_source_tree.binding_provenance import SubstitutionTraceV1


def _function(source: str):
    root = Path(tempfile.mkdtemp(prefix="loop-control-"))
    path = root / "subject.py"
    path.write_text(source, encoding="utf-8")
    return next(open_source_file_for_construction(path, root=root).functions())


def _returned(source: str):
    """The value the function's one completed arm returns."""
    return _function(source).sugar().desugar().completed_value().post().args[1].value


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
    # Items 0 and 1 run, item 2 breaks before its ``seen``; the else never
    # runs. Python returns 1.
    assert (
        _returned(
            "def arbitrary():\n"
            "    for renamed in (0, 1, 2, 3):\n"
            "        if renamed == 2:\n"
            "            break\n"
            "        seen = renamed\n"
            "    else:\n"
            "        seen = 99\n"
            "    return seen\n"
        )
        == 1
    )


def test_bounded_continue_routes_to_next_iteration_and_omits_tail():
    # Item 1 continues past ``kept = renamed``; item 2 runs it. Python
    # returns 2.
    assert (
        _returned(
            "def arbitrary():\n"
            "    kept = -1\n"
            "    for renamed in (0, 1, 2):\n"
            "        if renamed == 1:\n"
            "            continue\n"
            "        kept = renamed\n"
            "    return kept\n"
        )
        == 2
    )


def test_bounded_exhaustion_runs_else_and_exports_final_target_binding():
    # The else runs after the last item and reads the target's last value:
    # ``marker = 5 + 1``.
    assert (
        _returned(
            "def arbitrary():\n"
            "    marker = -1\n"
            "    for renamed in (4, 5):\n"
            "        marker = renamed\n"
            "    else:\n"
            "        marker = renamed + 1\n"
            "    return marker\n"
        )
        == 6
    )


def test_bounded_while_break_skips_else_with_exact_post_state():
    assert (
        _returned(
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
        == 2
    )


def test_bounded_while_continue_routes_to_test_backedge():
    assert (
        _returned(
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
        == 4
    )


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
    assert (
        _returned(
            "def arbitrary():\n"
            "    count = 0\n"
            "    for outer in (0, 1):\n"
            "        for inner in (0, 1):\n"
            "            break\n"
            "        count = count + 1\n"
            "    return count\n"
        )
        == 2
    )


def test_nested_continue_is_consumed_only_by_the_inner_bounded_loop():
    assert (
        _returned(
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
        == 22
    )


def test_loop_else_preserves_a_carried_name_it_never_rebinds():
    # A name carried through the loop (rebound in the body) that the else clause
    # does NOT touch keeps its loop-exhaustion value (regression: pandas
    # io/html, io/excel/_xlsxwriter, _version).
    assert (
        _returned(
            "def arbitrary():\n"
            "    total = 0\n"
            "    for i in (1, 2):\n"
            "        total = total + i\n"
            "    else:\n"
            "        seen = True\n"
            "    return total\n"
        )
        == 3
    )
