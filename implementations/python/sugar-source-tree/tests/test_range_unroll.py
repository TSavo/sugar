"""`for i in range(...)` over CONCRETE integer arguments runs in hand: a
completed ``range(...)`` over ground ints is the tuple of the ints it yields
(``iterator_operation.in_hand_iterable``), and the reduction runs the body
once per int through the loop's one item runner (#7757 new 6, #8957). No
rewrite unrolls it. A symbolic bound runs as the loop's recurrence.

Each file is opened through the one construction door under a workspace
root, as the lift opens it: the iteration's own ``StopIteration`` cites a
workspace-relative locus."""

import tempfile
from pathlib import Path

from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import ExitSet

from native_carrier_testimony import undecided_function_value


def _fn(src):
    root = Path(tempfile.mkdtemp(prefix="range-unroll-"))
    path = root / "subject.py"
    path.write_text(src, encoding="utf-8")
    return next(open_source_file_for_construction(path, root=root).functions())


def _invs(src):
    function = _fn(src)
    outcome = function.sugar().desugar()
    if isinstance(outcome, ExitSet) and outcome.completed_value() is not None:
        return outcome.completed_value().invs()
    # Each range-body equality over the formal is the undecided equality's two
    # faces: the universe completes under their completes atoms (#7757 NEW-1).
    return undecided_function_value(function, owner="UndecidedCompare:Eq").invs()


def _compared_items(invs):
    # Each inv is the truth of ``python:compare_result("Eq", i, z, <key>)``,
    # one key per item (#7757 NEW-1); the item is the compare's left operand.
    assert all(inv.name == "python:truth_result" for inv in invs), invs
    compared = [inv.args[0] for inv in invs]
    assert all(
        c.name == "python:compare_result"
        and c.args[0].value == "Eq"
        and c.args[2].name == "z"
        for c in compared
    ), compared
    assert len({c.args[-1] for c in compared}) == len(compared)
    return [c.args[1].value for c in compared]


def test_range_stop_unrolls_the_body_per_element():
    invs = _invs(
        "def A(z):\n    for i in range(3):\n        assert i == z\n    return z\n"
    )
    assert len(invs) == 3
    assert _compared_items(invs) == [0, 1, 2]


def test_range_start_stop_unrolls_the_body_per_element():
    invs = _invs(
        "def A(z):\n    for i in range(2, 5):\n        assert i == z\n    return z\n"
    )
    assert _compared_items(invs) == [2, 3, 4]


def test_range_start_stop_step_unrolls_the_body_per_element():
    invs = _invs(
        "def A(z):\n    for i in range(10, 0, -3):\n        assert i == z\n    return z\n"
    )
    assert _compared_items(invs) == [10, 7, 4, 1]


def test_empty_range_states_nothing():
    invs = _invs(
        "def A(z):\n    for i in range(0):\n        assert i == z\n    return z\n"
    )
    assert invs == ()


def test_loop_carried_accumulator_folds_over_a_concrete_range():
    # t = 0; for i in range(4): t = t + i; return t  -- folds to 0+1+2+3 = 6.
    post = (
        _fn(
            "def A():\n    t = 0\n    for i in range(4):\n        t = t + i\n    return t\n"
        )
        .sugar()
        .desugar()
        .completed_value()
        .post()
    )
    assert post.args[1].value == 6


def test_symbolic_range_bound_is_loop_recurrence():
    """Live law (replaces factory forall inv): symbolic range(n) is LoopRecurrenceSugar."""
    sugar = _fn(
        "def A(z, n):\n    for i in range(n):\n        assert i == z\n    return z\n"
    ).sugar()
    assert any(type(s).__name__ == "LoopRecurrenceSugar" for s in sugar.statements)
