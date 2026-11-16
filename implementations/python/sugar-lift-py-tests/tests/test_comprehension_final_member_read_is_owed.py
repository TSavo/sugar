"""A symbolic comprehension's final member, read, is the undecided member,
never a free term (#7757, step 6).

A lambda made in a comprehension and called after it reads the
comprehension's cell, its final member
(``EvaluationRefSugar._cell_at_the_call``).  Over an iterable whose
members are not in hand the comprehension runs as the loop's recurrence
(``ComprehensionSugar._recurrence``), and its final member is the
recurrence's value of each member coordinate after it,
``python:loop.recurrence(<generator coordinate>, <coordinate>)``
(``ComprehensionSugar._recurrence_final_ctx``,
``loop_recurrence_sugar.recurrence_head``), as a loop's target read after
it is.  No equation ties it to a member of the iterable, so at prove it is
a value the solver chooses.  Its read owes the undecided member by the one
rule (``read_of_bound_value``), as the recurrence's item's does (#8920).  A
finite comprehension's final member is the last member's own value and
reads as it is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_a_read_of_the_symbolic_final_member_is_owed() -> None:
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
        read_of_bound_value,
        recurrence_head,
    )

    final = SymbolicValue(recurrence_head("generator", "coordinate"))
    read = read_of_bound_value(final, None)
    assert read.completed_value() is final
    assert read.owed_items(), read


def test_a_finite_final_member_reads_as_it_is() -> None:
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import read_of_bound_value

    last = TermValue(2)
    assert read_of_bound_value(last, None) is last


# ``range(1000)`` is past the projection budget: the comprehension runs as its
# recurrence, and ``g`` reads its final member after it.  ``g()`` is 999.
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
