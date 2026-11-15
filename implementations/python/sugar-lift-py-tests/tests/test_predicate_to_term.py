"""PredicateValue projects its carried formula into the existing term spelling."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.floor import PredicateValue, SymbolicValue
from sugar_lift_py_tests.ir import (
    Int,
    and_,
    ctor,
    forall,
    make_var,
    not_,
    num,
    py_eq,
    py_truthy,
)


def test_atomic_predicates_reify_as_term_coordinates() -> None:
    value = make_var("value")
    assert PredicateValue(py_eq(value, num(1))).to_term(owner="test") == ctor(
        "py.eq", [value, num(1)]
    )
    assert PredicateValue(py_truthy(value)).to_term(owner="test") == ctor(
        "py.truthy", [value]
    )


def test_connective_predicates_reify_recursively() -> None:
    value = make_var("value")
    formula = and_([py_truthy(value), not_(py_eq(value, num(0)))])
    assert PredicateValue(formula).to_term(owner="test") == ctor(
        "py.and",
        [
            ctor("py.truthy", [value]),
            ctor("py.not", [ctor("py.eq", [value, num(0)])]),
        ],
    )


def test_different_predicates_project_to_different_terms() -> None:
    value = make_var("value")
    one = PredicateValue(py_eq(value, num(1))).to_term(owner="test")
    two = PredicateValue(py_eq(value, num(2))).to_term(owner="test")
    assert one != two


def test_predicate_can_ride_as_an_operation_operand() -> None:
    """A predicate is a ``bool`` operand: ``left + (value == 1)`` is an
    operation over it, with the predicate's own term as the right operand.
    ``left``'s type is undecided, so Python selects ``__add__`` /
    ``__radd__`` from a type this frame did not look at: the operation is
    the undecided member's two faces (``undecided_binary_faces``), never a
    sole completion that claims it cannot raise."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome import Completed, Halted

    site = "t.py:1:0"
    predicate = PredicateValue(py_eq(make_var("value"), num(1)))
    outcome = SymbolicValue(make_var("left")).add(predicate, site=site, ctx=None)
    (completed,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    (halted,) = [arm for arm in outcome.exits if isinstance(arm, Halted)]
    assert completed.value.to_term(owner="test") == ctor(
        "python:binary_result",
        (
            str_const("+"),
            make_var("left"),
            ctor("py.eq", [make_var("value"), num(1)]),
            str_const(occurrence_key(site)),
        ),
    )
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.producer_node_owner == "UndecidedBinary:+"


def test_quantified_predicate_projection_stays_loud() -> None:
    formula = forall("item", Int(), py_truthy(make_var("item")))
    with pytest.raises(ConstructionPanic, match="PredicateValue.to_term"):
        PredicateValue(formula).to_term(owner="test")
