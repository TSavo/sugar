"""A comprehension's symbolic member, read, is the undecided member, never a
free term (#7757, step 6).

Over an iterable whose members are not in hand a comprehension is evaluated
once, over its symbolic member (``ComprehensionSugar._symbolic_member_ctx``):
the variable its fold's lambda binds.  On the arms that complete the fold
binds it, and the fold's read owes (#8916).  An element's or condition's
halt arm never reaches the fold: its guard reads the member free.  Where the
iterable's ``iter`` and ``next`` are decided (a ``range`` past the unroll
budget) and the halt's own operation is decided (a ground ``1 // 0`` under a
test of the member), nothing else on that arm owed, and a claim about the
halt -- an ``except`` around the comprehension -- could read ``sat`` for a
lie by the solver choosing the member.  A read of the member now owes the
undecided member by the one rule (``read_of_bound_value``), so every arm
that follows the read, the halt included, owes; the halt still stands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _member():
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var

    return SymbolicValue(make_var("member"), recurrence_member=True)


def test_a_read_of_the_symbolic_member_is_owed() -> None:
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import read_of_bound_value

    member = _member()
    read = read_of_bound_value(member, None)
    assert read.completed_value() is member
    assert read.owed_items(), read


def test_an_unmarked_symbolic_value_reads_as_it_is() -> None:
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import read_of_bound_value

    value = SymbolicValue(make_var("member"))
    assert read_of_bound_value(value, None) is value


def test_a_guarded_value_with_the_member_on_one_face_holds_it() -> None:
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.ir import atomic, str_const
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
        holds_recurrence_value,
    )

    guard = atomic("python.test", [str_const("c")])
    assert holds_recurrence_value(GuardedValue(guard, TermValue(0), _member()))


# ``range(1, 1000)`` is past the unroll budget and iterating a range object
# never raises; ``1 // 0`` is a ground halt.  Only the member decides the
# halt's guard, and no member is falsy: ``f()`` is 1.
_RANGE = """\
def f():
    try:
        [1 // 0 if not i else 0 for i in range(1, 1000)]
        return 1
    except ZeroDivisionError:
        return 2


def test_f():
    assert f() == {v}
"""

# The owner's example: whatever ``xs`` holds, the claim about the halt is
# never decided by the solver choosing the member.
_FORMAL = """\
def f(xs):
    try:
        [1 // x for x in xs]
        return 1
    except ZeroDivisionError:
        return 2


def test_f():
    assert f([0]) == {v}
"""


@pytest.mark.parametrize(("source", "truth"), [(_RANGE, "1"), (_FORMAL, "2")])
def test_the_truthful_half_is_never_refuted(
    source: str, truth: str, tmp_path: Path
) -> None:
    result = run_source_through_real_solver(tmp_path / "t", source.format(v=truth))
    assert result.verdict != "unsat"


@pytest.mark.parametrize(("source", "lie"), [(_RANGE, "2"), (_FORMAL, "1")])
def test_the_lying_half_is_never_sat(source: str, lie: str, tmp_path: Path) -> None:
    # The halt's guard reads the member: it is not a choice the solver makes.
    result = run_source_through_real_solver(tmp_path / "l", source.format(v=lie))
    assert result.verdict != "sat"
