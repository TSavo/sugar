"""A symbolic comprehension's final member, read, is the undecided member,
never a free term (#7757, step 6).

A lambda made in a comprehension and called after it reads the
comprehension's cell, its final member
(``EvaluationRefSugar._cell_at_the_call``).  Over an iterable whose
members are not in hand that is
``python:comprehension.final_member(<iterable>, <coordinate>)``
(``ComprehensionSugar._symbolic_final_ctx``), and, for a destructuring
target, each leaf's projection of it.  No equation ties it to a member of
the iterable, so at prove it is a value the solver chooses.  Its read now owes
the undecided member by the one rule (``read_of_bound_value``), as the
symbolic member's does (#8920).  A finite comprehension's final member is the
last member's own value and reads as it is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_a_read_of_the_symbolic_final_member_is_owed() -> None:
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import read_of_bound_value

    final = SymbolicValue(
        ctor(
            "python:comprehension.final_member",
            [str_const("xs"), str_const("coordinate")],
            symbol_kind="coordinate",
        ),
        recurrence_member=True,
    )
    read = read_of_bound_value(final, None)
    assert read.completed_value() is final
    assert read.owed_items(), read


def test_a_finite_final_member_reads_as_it_is() -> None:
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import read_of_bound_value

    last = TermValue(2)
    assert read_of_bound_value(last, None) is last


# ``range(1000)`` is past the projection budget: the comprehension is its
# fold, and ``g`` reads its final member after it.  ``g()`` is 999.
_RANGE = """\
def f():
    [(g := lambda: i) for i in range(1000)]
    return g()


def test_f():
    assert f() == {v}
"""


def test_the_truthful_half_is_never_refuted(tmp_path: Path) -> None:
    result = run_source_through_real_solver(tmp_path / "t", _RANGE.format(v="999"))
    assert result.verdict != "unsat"


@pytest.mark.parametrize("lie", ["5", "-1"])
def test_the_lying_half_is_never_sat(lie: str, tmp_path: Path) -> None:
    # The final member is not a choice the solver makes.
    result = run_source_through_real_solver(tmp_path / "l", _RANGE.format(v=lie))
    assert result.verdict != "sat"
