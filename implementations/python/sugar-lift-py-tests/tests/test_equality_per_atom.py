from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.floor import (
    OpaqueOpCallsite,
    PredicateValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import eq, make_var, py_eq
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.proofir.formulas import Eq
from sugar_lift_py_tests.proofir.sorts import IntSort, RealSort
from sugar_lift_py_tests.proofir.terms import ConstTerm


def _equality(left, right) -> PredicateValue:
    value = complete_value(left.equals(right, "assertion"), owner="test equality")
    assert isinstance(value, PredicateValue)
    return value


def test_same_sort_int_warrant_emits_fol_equality_only() -> None:
    call = OpaqueOpCallsite("len", TermValue(7), computed=TermValue(1))

    predicate = _equality(call, TermValue(1))

    assert predicate.formula == eq(
        call.to_term(owner="test"), TermValue(1).to_term(owner="test")
    )
    assert predicate.formula != py_eq(
        call.to_term(owner="test"), TermValue(1).to_term(owner="test")
    )


def test_mixed_int_real_warrant_emits_py_eq_and_explicit_promotion_bridge() -> None:
    call = OpaqueOpCallsite("len", TermValue(7), computed=TermValue(1))

    predicate = _equality(call, TermValue(1.5))

    assert predicate.formula == py_eq(
        call.to_term(owner="test"), TermValue(1.5).to_term(owner="test")
    )
    assert predicate.formula != eq(
        call.to_term(owner="test"), TermValue(1.5).to_term(owner="test")
    )
    assert len(predicate.derived_formulas) == 2
    promotion = predicate.derived_formulas[1]
    assert promotion.kind == "implies"
    assert promotion.operands[0] == predicate.formula
    promoted_eq = promotion.operands[1]
    assert promoted_eq.name == "="
    assert promoted_eq.args[0].name == "to_real"


def test_opaque_equality_stays_py_eq_without_sort_bridge() -> None:
    opaque = SymbolicValue(make_var("opaque"))

    predicate = _equality(opaque, TermValue(1))

    assert predicate.formula == py_eq(
        make_var("opaque"), TermValue(1).to_term(owner="test")
    )
    assert predicate.derived_formulas == ()


def test_typed_eq_rejects_mixed_numeric_sorts_without_explicit_promotion() -> None:
    with pytest.raises(FactoryPanic, match="matching sorts for Eq"):
        Eq(ConstTerm(1, sort=IntSort()), ConstTerm("1.0", sort=RealSort()))
