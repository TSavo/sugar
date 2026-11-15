"""A live loop's symbolic item, read through the target, is the undecided
member, never a free term (#7757, step 6).

A live loop over what the reduction has not decided runs as its recurrence:
one symbolic item, whose target is bound to the item of the iterable,
``python:loop.item(<loop>, <iterable>)``
(``LoopRecurrenceSugar._enter_symbolic_item``).  Nothing states anything
else about that term: no equation ties it to a member of the iterable, so at
prove it is a value the solver chooses.  Where the iterable's ``iter`` and
``next`` are decided (a ``range`` past the unroll budget, a decided builtin
container) nothing else on the path owes, and a claim over the item -- a
branch on it, a value written from it -- could read ``sat`` for a lie.  A
read of the item through the target's key now owes the undecided member by
the one rule a recurrence head's read owes by (``read_of_bound_value``,
#8906).  A decided item (a member of an in-hand list, tuple or ground
range) is never the symbolic item: the loop runs unrolled over it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _item():
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import LOOP_ITEM

    return SymbolicValue(
        ctor(
            LOOP_ITEM,
            [str_const("blake3-512:loop"), str_const("blake3-512:xs")],
            symbol_kind="coordinate",
        )
    )


def test_a_read_of_the_symbolic_item_is_owed() -> None:
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import read_of_bound_value

    item = _item()
    read = read_of_bound_value(item, None)
    assert read.completed_value() == item
    assert read.owed_items(), read


def test_a_guarded_value_with_the_item_on_one_face_holds_it() -> None:
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.ir import atomic, str_const
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
        holds_recurrence_value,
    )

    guard = atomic("python.test", [str_const("c")])
    assert holds_recurrence_value(GuardedValue(guard, _item(), TermValue(0)))


# ``range(1000)`` is past the unroll budget: the loop runs as its
# recurrence, and iterating a range object never raises, so no ``iter`` or
# ``next`` owes.  The item is the only thing the branch reads.
_RANGE = """\
def f():
    for i in range(1000):
        if i < 0:
            return 1
    return 0


def test_f():
    assert f() == {v}
"""

# ``xs`` is a formal: the item is written to a name the loop does not carry.
_LAST = """\
def g(xs):
    last = 0
    for x in xs:
        last = x
    return last


def test_g():
    assert g([1, 2]) == {v}
"""


@pytest.mark.parametrize(("source", "truth"), [(_RANGE, 0), (_LAST, 2)])
def test_the_truthful_half_is_never_refuted(
    source: str, truth: int, tmp_path: Path
) -> None:
    result = run_source_through_real_solver(tmp_path / "t", source.format(v=truth))
    assert result.verdict != "unsat"


@pytest.mark.parametrize(("source", "lie"), [(_RANGE, 1), (_LAST, 7)])
def test_the_lying_half_is_never_sat(source: str, lie: int, tmp_path: Path) -> None:
    # Whatever the item is: it is not a choice the solver makes.
    result = run_source_through_real_solver(tmp_path / "l", source.format(v=lie))
    assert result.verdict != "sat"
