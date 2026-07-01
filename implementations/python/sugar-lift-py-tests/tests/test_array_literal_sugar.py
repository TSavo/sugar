"""ArrayLiteralSugar reduces a Python list literal to the `array` ctor, recursively
for nested lists."""

from __future__ import annotations

import pytest

from factory_reduce import fol, reduce_term, reduce_value

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.ir import ctor, num


def test_flat_list_reduces_to_array_ctor():
    assert fol(reduce_term("[1, 2, 3]")) == fol(ctor("array", [num(1), num(2), num(3)]))


def test_nested_list_reduces_to_nested_array_ctor():
    expected = ctor(
        "array",
        [ctor("array", [num(1), num(2)]), ctor("array", [num(3), num(4)])],
    )
    assert fol(reduce_term("[[1, 2], [3, 4]]")) == fol(expected)


def test_tuple_element_reduces_to_tuple_inside_array_ctor():
    expected = ctor("array", [ctor("tuple", [num(1), num(2)])])

    assert fol(reduce_term("[(1, 2)]")) == fol(expected)


def test_array_element_floor_gap_blames_the_element_source():
    with pytest.raises(FactoryGap) as raised:
        reduce_value("['x']")

    assert raised.value.info == {
        "owner": "ArrayLiteralSugar",
        "blame": "t.py:1:1",
        "observed": "StringValue",
        "requested": "array element floor",
        "fix": "add ArrayLiteral element floor for StringValue",
    }
