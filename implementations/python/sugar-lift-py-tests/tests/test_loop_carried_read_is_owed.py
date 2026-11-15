"""A live loop's carried name, read as the recurrence's value, is the
undecided member, never a free term (#7757, step 6).

A live loop over what the reduction has not decided runs as its recurrence.
Each name it carries (read before it is written in the body, as an
accumulator ``total += x`` is) is bound, on every exit, to the recurrence's
value of it, ``python:loop.recurrence(<loop>, <key>)``
(``LoopRecurrenceSugar._recurrence_head``).  The only statement made about
that value is ``head = python:loop.step(head, ...)``, and the step is
uninterpreted: nothing at prove constrains it, so a claim over the name read
after the loop was decided by a value the solver chose, and a lie could read
``sat``.  A read of the recurrence's value now owes the undecided member
(``branch_result_coordinate.undecided_slot_debt``), as #8899 made a write
slot nothing decided owe: after the loop (``LoopBindingRefSugar``), and in
its ``else`` suite or symbolic item through the header
(``EvaluationRefSugar``), by one rule (``read_of_bound_value``).  A value a
concrete loop leaves reads as it is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _head():
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import RECURRENCE_HEAD

    return SymbolicValue(
        ctor(
            RECURRENCE_HEAD,
            [str_const("blake3-512:loop"), str_const("blake3-512:total")],
            symbol_kind="coordinate",
        )
    )


def test_a_read_of_the_recurrences_value_is_owed() -> None:
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import read_of_bound_value

    head = _head()
    read = read_of_bound_value(head, None)
    assert read.completed_value() == head
    assert read.owed_items(), read


def test_a_guarded_value_with_the_recurrence_on_one_face_is_owed() -> None:
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.ir import atomic, str_const
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
        holds_recurrence_value,
    )

    guard = atomic("python.test", [str_const("c")])
    assert holds_recurrence_value(GuardedValue(guard, TermValue(0), _head()))


def test_a_concrete_loops_value_reads_as_it_is() -> None:
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import read_of_bound_value

    value = TermValue(3)
    assert read_of_bound_value(value, None) is value


# ``xs`` and ``n`` are formals of ``f`` and ``g``, so each loop runs as its
# recurrence in its own contract; the accumulator is carried, and the read
# after the loop is the recurrence's value.
_FOR = """\
def f(xs):
    t = 0
    for x in xs:
        t += x
    return t


def test_f():
    assert f([1, 2]) == {v}
"""

_WHILE = """\
def g(n):
    i = 0
    while i < n:
        i += 1
    return i


def test_g():
    assert g(3) == {v}
"""


@pytest.mark.parametrize(("source", "truth"), [(_FOR, 3), (_WHILE, 3)])
def test_the_truthful_half_is_never_refuted(
    source: str, truth: int, tmp_path: Path
) -> None:
    result = run_source_through_real_solver(tmp_path / "t", source.format(v=truth))
    assert result.verdict != "unsat"


@pytest.mark.parametrize("source", [_FOR, _WHILE])
@pytest.mark.parametrize("lie", [-1, 7])
def test_the_lying_half_is_never_sat(source: str, lie: int, tmp_path: Path) -> None:
    # Whatever the recurrence's value: it is not a choice the solver makes.
    result = run_source_through_real_solver(tmp_path / "l", source.format(v=lie))
    assert result.verdict != "sat"
