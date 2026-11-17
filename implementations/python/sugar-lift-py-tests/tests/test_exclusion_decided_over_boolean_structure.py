"""A completed face is factored when its guards' boolean structure excludes
the arms, read off the formulas themselves (#7757).

``ExitSet.factor_completed`` refused 112 pandas and 53 numpy functions on the
lane at 13e3413ad (``... arms are not provably exclusive``). The literal
reading (``g`` against ``not g`` among flattened conjuncts) cannot see an
exclusion an equal-destination merge spells as a disjunction (``normalize``
disjoins the contributors' guards), nor one a complement spells around a
conjunction (``not (a and b)`` against ``a and b and c``). Both are decided
now: every atom an opaque proposition, the pair exclusive exactly when no
truth assignment makes both guards true.

Twins. Truthful: arms whose guards are exclusive in every assignment factor
into one arm, the first arm's value under its own guard. Lying: arms whose
guards hold together under some assignment are refused by name, as before,
including the merged ``g or X`` against ``not g`` the earlier refutation
pinned (``X`` free).
"""

from __future__ import annotations

import sys

import pytest

from sugar_lift_py_tests.ir import and_, atomic, implies, make_var, not_, or_
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    ExitSetFactoringGap,
    _are_exclusive,
)


def _g(name: str):
    return atomic(name, [make_var("state")])


def _factor(left_guard, right_guard):
    return ExitSet(
        (Completed(left_guard, "one"), Completed(right_guard, "two"))
    ).factor_completed()


def test_a_merged_arm_is_exclusive_with_a_sibling_every_contributor_excluded():
    a, b = _g("a"), _g("b")
    merged = or_([and_([a, b]), not_(a)])  # two arms with one value, disjoined
    sibling = and_([a, not_(b)])

    factored = _factor(merged, sibling)

    (arm,) = factored.exits
    assert arm.value.guard == merged
    assert arm.value.when_true == "one"
    assert arm.value.when_false == "two"


def test_a_complement_around_a_conjunction_is_an_exclusion():
    a, b, c = _g("a"), _g("b"), _g("c")
    left = not_(and_([a, b]))
    right = and_([a, b, c])

    assert _are_exclusive(left, right)
    assert len(_factor(left, right).exits) == 1


def test_an_implication_is_read_as_its_boolean_structure():
    a, b = _g("a"), _g("b")
    left = and_([implies(a, b), a])
    right = not_(b)

    assert _are_exclusive(left, right)
    assert len(_factor(left, right).exits) == 1


def test_guards_that_hold_together_under_some_assignment_are_still_refused():
    c, q = _g("c"), _g("q")

    assert not _are_exclusive(c, or_([not_(c), q]))  # both hold where q does
    with pytest.raises(ExitSetFactoringGap, match="not provably exclusive"):
        _factor(c, or_([not_(c), q]))


def test_the_merged_disjunction_with_a_free_disjunct_is_still_refused():
    g, prefix, free = _g("g"), _g("prefix0"), _g("prefix9")
    merged = and_([prefix, or_([g, free])])
    sibling = and_([prefix, not_(g)])

    assert not _are_exclusive(merged, sibling)
    with pytest.raises(ExitSetFactoringGap):
        _factor(merged, sibling)


def test_unrelated_atoms_are_never_exclusive():
    with pytest.raises(ExitSetFactoringGap):
        _factor(_g("p"), and_([_g("p"), _g("r")]))


def test_a_guard_deeper_than_the_stack_is_decided_without_recursion():
    g = _g("g")
    deep = _g("leaf")
    for index in range(sys.getrecursionlimit() + 100):
        deep = and_([_g(f"p{index % 5}"), not_(deep)])
    left = not_(or_([g, deep]))  # forces g false
    right = and_([g, _g("r")])

    assert _are_exclusive(left, right)


def test_a_spent_budget_is_not_a_proof():
    a, b = _g("a"), _g("b")
    merged = or_([and_([a, b]), not_(a)])
    sibling = and_([a, not_(b)])

    assert not _are_exclusive(merged, sibling, [0])
    assert _are_exclusive(merged, sibling)
