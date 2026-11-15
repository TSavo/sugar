"""A slot nothing on the path decides or reads is the undecided member,
never a free flag (#7757, step 6).

A live loop over what the reduction has not decided runs as its recurrence
and leaves each name its items write bound through its post-loop key, read
after the loop as ``<post-loop key> if <an item wrote it> else <the binding
before the loop>`` (``nodes._live_loop_publication``).  The recurrence
states no condition under which an item wrote the name, so the write slot
(``loop_write_slot``) was read as its coordinate,
``py.truthy(python:branch_result(<slot>))``, which no contract row ties to
any input: the contract stated a value the solver could select by choosing
the flag, and a lie could read ``sat``.  Such a read now owes the undecided
member (``branch_result_coordinate.undecided_slot_debt``), as every
operation not decided here does; a slot the path decided (a concrete
loop's exit) or read as a test (a symbolic ``if``) owes nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _root():
    from sugar_lift_py_tests.context import ReduceContext

    return ReduceContext.root(owner="test_undecided_slot_read_is_owed")


def _write_slot():
    from sugar_source_tree.binding_state import loop_write_slot

    return loop_write_slot("blake3-512:post")


def _read(slot, ctx):
    from sugar_lift_py_tests.sugar.branch_result_ref_sugar import (
        BranchResultRefSugar,
    )

    return BranchResultRefSugar(slot=slot, site=None).desugar(ctx)


def test_a_write_slot_no_exit_decided_is_owed() -> None:
    from sugar_lift_py_tests.floor.branch_result_coordinate import (
        BranchResultCoordinate,
    )

    read = _read(_write_slot(), _root())
    assert isinstance(read.completed_value(), BranchResultCoordinate)
    assert read.owed_items(), read


@pytest.mark.parametrize("wrote", [True, False])
def test_a_write_slot_the_exit_decided_owes_nothing(wrote: bool) -> None:
    from sugar_lift_py_tests.floor.branch_result_coordinate import (
        BranchResultDecision,
    )

    slot = _write_slot()
    ctx = BranchResultDecision(slot, wrote, None).extend_scope(_root())
    read = _read(slot, ctx)
    assert read.owed_items() == (), read


def test_a_slot_read_as_its_test_owes_nothing() -> None:
    from sugar_lift_py_tests.floor.branch_result_coordinate import (
        slots_read_as_tests,
    )
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import atomic, str_const

    slot = _write_slot()
    test = atomic("python.test", [str_const("c")])
    ctx = slots_read_as_tests(_root(), ((slot.slot_id, test),))
    read = _read(slot, ctx)
    assert isinstance(read.completed_value(), PredicateValue)
    assert read.owed_items() == (), read


# A live ``while`` over a test no input decides on the formal (an identity,
# which owes nothing): ``y`` is written in the body, so its read after the
# loop selects by the loop's write slot.
_WHILE = """\
def f(x):
    y = 0
    while x is None:
        y = 1
        x = 2
    return y


def test_f():
    assert f(None) == {v}
"""


def test_the_truthful_half_is_never_refuted(tmp_path: Path) -> None:
    result = run_source_through_real_solver(tmp_path / "t", _WHILE.format(v=1))
    assert result.verdict != "unsat"


@pytest.mark.parametrize("lie", [0, 7])
def test_the_lying_half_is_never_sat(lie: int, tmp_path: Path) -> None:
    # Whatever the flag: the write slot is not a choice the solver makes.
    result = run_source_through_real_solver(tmp_path / "l", _WHILE.format(v=lie))
    assert result.verdict != "sat"
