"""A comprehension's symbolic fold, read, is the undecided member, never a
free term (#7757, step 6).

A comprehension over an iterable whose members are not in hand stays its
symbolic fold (``ComprehensionSugar._complete``): a ``ComprehensionValue``
holding its own coordinate, ``py.listcomp(<occurrence>)`` (or its set, dict
or generator kind, ``ComprehensionSugar._own_coordinate``).  Prove does not
interpret that constructor, so what the
comprehension accumulates is a value the solver chooses.  Where the
iterable's ``iter`` and ``next`` are decided (a ``range`` object, a decided
builtin container) nothing else on the path owed, and a claim over the fold
could read ``sat`` for a lie.  The comprehension completing with its fold,
and any read of a key that holds it, now owes the undecided member by the
one rule a live loop's recurrence value owes by (``read_of_bound_value``,
#8906).  A comprehension whose owner projected every member
(``finite_elements``) is decided and reads as it is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _fold(finite_elements=None):
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.ir import ctor, str_const

    return ComprehensionValue(
        ctor("py.listcomp", [str_const("xs")], symbol_kind="coordinate"),
        finite_elements=finite_elements,
    )


def test_a_read_of_a_symbolic_fold_is_owed() -> None:
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import read_of_bound_value

    fold = _fold()
    read = read_of_bound_value(fold, None)
    assert read.completed_value() == fold
    assert read.owed_items(), read


def test_a_fold_with_every_member_projected_reads_as_it_is() -> None:
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import read_of_bound_value

    fold = _fold(finite_elements=(TermValue(1), TermValue(2)))
    assert read_of_bound_value(fold, None) is fold


def test_a_guarded_value_with_a_fold_on_one_face_holds_it() -> None:
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.ir import atomic, str_const
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
        holds_recurrence_value,
    )

    guard = atomic("python.test", [str_const("c")])
    assert holds_recurrence_value(GuardedValue(guard, TermValue(0), _fold()))


# ``xs`` is a formal: the comprehension is its symbolic fold.
_FORMAL = """\
def f(xs):
    ys = [x for x in xs]
    return len(ys)


def test_f():
    assert f([1, 2]) == {v}
"""

# ``range(1000)`` is past the unroll budget, and iterating a range object
# never raises: no ``iter`` or ``next`` owes, only the fold is read.
_RANGE = """\
def g():
    return [i for i in range(1000)]


def test_g():
    assert g() == {v}
"""


@pytest.mark.parametrize(
    ("source", "truth"), [(_FORMAL, "2"), (_RANGE, "list(range(1000))")]
)
def test_the_truthful_half_is_never_refuted(
    source: str, truth: str, tmp_path: Path
) -> None:
    result = run_source_through_real_solver(tmp_path / "t", source.format(v=truth))
    assert result.verdict != "unsat"


@pytest.mark.parametrize(("source", "lie"), [(_FORMAL, "5"), (_RANGE, "[5]")])
def test_the_lying_half_is_never_sat(source: str, lie: str, tmp_path: Path) -> None:
    # Whatever the fold accumulates: it is not a choice the solver makes.
    result = run_source_through_real_solver(tmp_path / "l", source.format(v=lie))
    assert result.verdict != "sat"
