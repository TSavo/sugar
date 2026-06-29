"""ArrayLiteralSugar reduces a Python list literal to the `array` ctor, recursively
for nested lists."""
from __future__ import annotations

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.ir import ctor, num


def test_flat_list_reduces_to_array_ctor():
    assert fol(reduce_term("[1, 2, 3]")) == fol(ctor("array", [num(1), num(2), num(3)]))


def test_nested_list_reduces_to_nested_array_ctor():
    expected = ctor(
        "array",
        [ctor("array", [num(1), num(2)]), ctor("array", [num(3), num(4)])],
    )
    assert fol(reduce_term("[[1, 2], [3, 4]]")) == fol(expected)
