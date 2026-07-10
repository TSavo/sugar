"""AddSugar is a leaf BODY sugar on the array-map path: it reduces `x + n` to the
concrete sum when `x` is a bound element. Supporting `*`, `[]`, string concat, ...
is MORE SUGAR (more leaf bodies), never a smarter Map or Lambda."""

from __future__ import annotations

import pytest

from factory_reduce import array_map_reduce

from sugar_lift_py_tests.factory import factory_panic
from sugar_lift_py_tests.floor import ArrayLiteral, TermValue
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.operations import AddOperation


def test_add_reduces_bound_element_plus_addend():
    assert array_map_reduce("x + 1", {"x": TermValue(5)}) == TermValue(6)
    assert array_map_reduce("x + 0", {"x": TermValue(9)}) == TermValue(9)
    assert array_map_reduce("x + 10", {"x": TermValue(2)}) == TermValue(12)


def test_add_array_with_tuple_element_names_the_missing_floor():
    receiver = ArrayLiteral((TupleLiteralValue((TermValue(1), TermValue(2))),))

    with pytest.raises(FactoryGap) as raised:
        receiver.add_with(
            AddOperation(operand=TermValue(1), owner="AddSugar", blame="t.py:1:0"),
            ctx=None,
        )

    assert raised.value.info.to_json() == {
        "owner": "AddSugar",
        "blame": "t.py:1:0",
        "observed": "ArrayLiteral[TupleLiteralValue]+TermValue",
        "requested": "add operand floor",
        "fix": "add AddOperation support for ArrayLiteral[TupleLiteralValue] with TermValue",
        "gap_kind": "Floor",
        "gap_locus": "Construction",
    }


def test_add_array_with_non_term_addend_names_the_missing_floor():
    receiver = ArrayLiteral((TermValue(1),))

    with pytest.raises(FactoryGap) as raised:
        receiver.add_with(
            AddOperation(
                operand=ArrayLiteral((TermValue(2),)),
                owner="AddSugar",
                blame="t.py:1:0",
            ),
            ctx=None,
        )

    assert raised.value.info.to_json() == {
        "owner": "AddSugar",
        "blame": "t.py:1:0",
        "observed": "ArrayLiteral+ArrayLiteral",
        "requested": "add operand floor",
        "fix": "add AddOperation support for ArrayLiteral with ArrayLiteral",
        "gap_kind": "Floor",
        "gap_locus": "Construction",
    }
