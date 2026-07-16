from __future__ import annotations

from factory_reduce import reduce_value

from sugar_lift_py_tests.floor import (
    OpaqueOpCallsite,
    PredicateValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import lte, make_var, num, py_ge, py_le, py_lt
from sugar_lift_py_tests.outcome import complete_value


def _predicate(outcome) -> PredicateValue:
    value = complete_value(outcome, owner="test comparison")
    assert isinstance(value, PredicateValue)
    return value


def test_unbound_less_equal_uses_faithful_operator_atom_not_negated_lt() -> None:
    month = SymbolicValue(make_var("month"))

    value = reduce_value("month <= 12", binds={"month": month})

    assert isinstance(value, PredicateValue)
    assert value.formula == py_le(make_var("month"), num(12))
    assert value.formula.name == "py.le"
    assert value.formula != py_lt(num(12), make_var("month"))


def test_unbound_greater_equal_uses_faithful_operator_atom() -> None:
    left = SymbolicValue(make_var("left"))
    right = SymbolicValue(make_var("right"))

    value = reduce_value("left >= right", binds={"left": left, "right": right})

    assert isinstance(value, PredicateValue)
    assert value.formula == py_ge(make_var("left"), make_var("right"))


def test_warranted_less_equal_discharges_to_fol_atom() -> None:
    call = OpaqueOpCallsite("month", TermValue(7), computed=TermValue(11))

    predicate = _predicate(call.less_equal(TermValue(12), "assertion"))

    assert predicate.formula == lte(call.to_term(owner="test"), num(12))
    assert predicate.formula.name == "≤"
    assert predicate.formula != py_le(call.to_term(owner="test"), num(12))


def test_chained_and_standalone_less_equal_emit_the_same_atom() -> None:
    month = SymbolicValue(make_var("month"))
    standalone = reduce_value("month <= 12", binds={"month": month})
    chained = reduce_value("1 <= month <= 12", binds={"month": month})

    assert isinstance(standalone, PredicateValue)
    assert isinstance(chained, PredicateValue)
    assert chained.formula.kind == "and"
    assert chained.formula.operands[1] == standalone.formula
    assert standalone.formula.name == "py.le"
