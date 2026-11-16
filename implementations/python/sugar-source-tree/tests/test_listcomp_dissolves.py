"""``[e for x in <members in hand>]`` runs member by member through the loop's
one item runner and states the list it builds (#7757 new 6, #8957): no
rewrite dissolves it. Over an iterable whose members are not in hand it runs
as the loop's recurrence and completes with its own coordinate.

Each file is opened through the one construction door under a workspace
root, as the lift opens it."""

import tempfile
from pathlib import Path

from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Completed, ExitSet

from native_carrier_testimony import (
    atoms_named,
    completed_function_value,
    undecided_outcome,
    undetermined_owners,
)


def _fn(src):
    root = Path(tempfile.mkdtemp(prefix="listcomp-"))
    path = root / "subject.py"
    path.write_text(src, encoding="utf-8")
    return next(open_source_file_for_construction(path, root=root).functions())


def _out(src):
    return completed_function_value(_fn(src)).post().args[1]


def test_identity_comprehension_is_the_display():
    t = _out("def A():\n    return [x for x in [1, 2, 3]]\n")
    assert t.name == "array" and [a.value for a in t.args] == [1, 2, 3]


def test_mapped_comprehension_folds_per_element():
    t = _out("def A():\n    return [x + 10 for x in [1, 2]]\n")
    assert [a.value for a in t.args] == [11, 12]


def test_tuple_target_comprehension_destructures():
    t = _out("def A():\n    return [a + b for a, b in [(1, 2), (3, 4)]]\n")
    assert [a.value for a in t.args] == [3, 7]


def test_composes_with_len():
    # Every member is in hand: the list's length is decided
    # (``ComprehensionValue.length``).
    t = _out("def A():\n    return len([x for x in [1, 2, 3]])\n")
    assert t.value == 3


def test_comprehension_over_range_dissolves():
    # A completed ``range(...)`` over ground ints is the ints it yields
    # (``iterator_operation.in_hand_iterable``).
    t = _out("def A():\n    return [x + 1 for x in range(3)]\n")
    assert t.name == "array" and [a.value for a in t.args] == [1, 2, 3]


def test_undecidable_filtered_comprehension_is_typed_filter_guard():
    """The filter over the formal waits on no caller: it is the undecided
    ordering's two faces (#7757 NEW-1), never a guessed verdict. Which
    members it keeps is not decided, so the comprehension runs as its
    recurrence and the ordering's operand is its one symbolic item."""
    outcome = undecided_outcome(
        _fn("def A(limit):\n    return [x for x in [1, 2] if x > limit]\n")
    )
    assert "UndecidedCompare:Gt" in undetermined_owners(outcome)
    compares = {
        (operation.args[0].value, operation.args[1].name, operation.args[2].name)
        for atom in atoms_named(outcome, "python:compare.completes")
        for operation in atom.args
    }
    assert compares == {("Gt", "python:loop.item", "limit")}


def test_symbolic_comprehension_builds_coordinate():
    """Over a formal: ``iter(xs)`` is stated, and every completed arm
    returns the comprehension's own coordinate,
    ``py.listcomp(<occurrence>, <evaluation key>)``, whose read owes."""
    outcome = _fn("def A(xs):\n    return [x for x in xs]\n").sugar().desugar()
    assert isinstance(outcome, ExitSet), outcome
    terms = [
        exit_.value.post().args[1]
        for exit_ in outcome.normalize().exits
        if isinstance(exit_, Completed)
    ]
    assert terms, outcome
    for t in terms:
        assert t.name == "py.listcomp"
        assert [arg.name for arg in t.args] == [
            "python:source-occurrence",
            "python:occurrence",
        ]
    assert atoms_named(outcome, "python:iter_op.completes"), outcome
    assert outcome.owed_items(), outcome
