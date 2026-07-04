"""ArrayLiteralSugar reduces a Python list literal to the `array` ctor, recursively
for nested lists."""

from __future__ import annotations

from factory_reduce import fol, reduce_term, reduce_value

from sugar_lift_py_tests.floor import BoolValue, StringValue, TermValue
from sugar_lift_py_tests.ir import bool_const, ctor, num, str_const


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


def test_string_element_reduces_to_string_const_inside_array_ctor():
    expected = ctor("array", [str_const("x")])

    assert fol(reduce_term("['x']")) == fol(expected)


def test_string_array_element_is_structural_not_swallowed():
    value = reduce_value("['x']")

    assert value.items == (StringValue("x"),)
    assert value.items != (TermValue(0),)


def test_bool_element_reduces_to_bool_const_inside_array_ctor():
    expected = ctor("array", [bool_const(True)])

    assert fol(reduce_term("[True]")) == fol(expected)


def test_bool_array_element_is_structural_not_swallowed():
    value = reduce_value("[True]")

    assert value.items == (BoolValue(True),)
    assert value.items != (TermValue(1),)
