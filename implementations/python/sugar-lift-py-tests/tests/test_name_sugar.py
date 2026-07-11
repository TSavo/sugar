"""NameSugar and the symbolic spine. A name is nothing: it asks the temporal
context what stands there, and the binding answers (unbound panics, the same
way it would for Python). Comparison over a symbolic side EMITS a
PredicateValue instead of folding -- fold when both sides are ground, emit
when either side stands on the term floor, panic only inside to_term when a
side cannot enter FOL at all."""

from __future__ import annotations

import pytest

from factory_reduce import fol, reduce_term, reduce_value

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import PredicateValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var, num, py_eq


def test_name_reduces_to_its_bound_variable():
    got = reduce_term("x", {"x": SymbolicValue(make_var("x"))})
    assert fol(got) == fol(make_var("x"))


def test_name_reduces_to_its_concrete_binding() -> None:
    assert reduce_value("x", binds={"x": TermValue(3)}) == TermValue(3)


def test_unbound_name_panics_like_python_would() -> None:
    with pytest.raises(FactoryPanic):
        reduce_value("x")


def test_symbolic_left_equals_emits_the_formula() -> None:
    value = reduce_value("z == 1", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == py_eq(make_var("z"), num(1))


def test_concrete_left_equals_symbolic_right_emits_too() -> None:
    # `1 == z`: the concrete left cannot fold against a symbolic right; the
    # equals floor emits -- never a false panic, nothing is missing here.
    value = reduce_value("1 == z", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == py_eq(num(1), make_var("z"))


def test_ground_sides_still_fold_not_emit() -> None:
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    assert isinstance(reduce_value("1 == 1"), TrueBoolLiteralSugar)


def test_a_value_with_no_term_projection_still_panics() -> None:
    # None cannot fold against a number and NoneValue has no to_term: the
    # panic moved INTO the term floor, and it still fires.
    with pytest.raises(FactoryPanic):
        reduce_value("None == 5")
