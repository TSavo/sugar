"""Symbolic comparisons emit operator-indexed atoms (py.eq / py.lt). The sort
universe adjudicates the interpretation later -- on Int, py.eq strengthens to
SMT =; on NaN-bearing Real it is IEEE eq (not reflexive). The lift must not
own reflexivity: nan == nan is False in Python, so py.eq(z, z) is not SMT =."""

from __future__ import annotations

from factory_reduce import reduce_value

from sugar_lift_py_tests.floor import PredicateValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var, py_eq


def test_symbolic_equals_emits_py_eq_not_smt_eq() -> None:
    # z == z must be py.eq(z, z): SMT = is reflexive, Python float == is not
    # (nan == nan is False). The atom is the join key; the sort adjudicates.
    value = reduce_value("z == z", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == py_eq(make_var("z"), make_var("z"))
