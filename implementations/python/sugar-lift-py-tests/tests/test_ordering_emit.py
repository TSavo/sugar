"""The ordering floor under the fold/emit/panic contract: fold when both sides
are ground, EMIT a PredicateValue lt(l, r) when either side stands on the term
floor, panic only inside to_term when a side cannot enter FOL at all. Mirrors
the landed equals emit with lt instead of eq."""

from __future__ import annotations

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import PredicateValue, SymbolicValue
from sugar_lift_py_tests.ir import lt, make_var, not_, num
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def test_symbolic_left_less_than_emits_the_formula() -> None:
    value = reduce_value("z < 1", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == lt(make_var("z"), num(1))


def test_concrete_left_less_than_symbolic_right_emits_too() -> None:
    # `1 < z`: the concrete left cannot fold against a symbolic right; the
    # ordering floor emits -- never a false panic, nothing is missing here.
    value = reduce_value("1 < z", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == lt(num(1), make_var("z"))


def test_greater_than_emits_swapped_less_than() -> None:
    # `>` is `b < a` with the operands swapped; emission preserves that.
    value = reduce_value("z > 1", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == lt(num(1), make_var("z"))


def test_less_equal_emits_negated_swapped_less_than() -> None:
    # `<=` is `not (b < a)`: the floor emits lt(1, z), then PredicateValue.negate.
    value = reduce_value("z <= 1", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == not_(lt(num(1), make_var("z")))


def test_ground_sides_still_fold_not_emit() -> None:
    assert isinstance(reduce_value("1 < 2"), TrueBoolLiteralSugar)


def test_a_value_with_no_term_projection_still_panics() -> None:
    # None cannot fold against a number and NoneValue has no to_term: the
    # panic lives on the term floor, and it still fires.
    with pytest.raises(FactoryPanic):
        reduce_value("None < 5")
