"""TupleLiteralSugar reduces a Python tuple literal to the `tuple` ctor."""
from __future__ import annotations

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.ir import ctor, num


def test_tuple_reduces_to_tuple_ctor() -> None:
    assert fol(reduce_term("(1, 1)")) == fol(ctor("tuple", [num(1), num(1)]))


def test_singleton_tuple_reduces_to_tuple_ctor() -> None:
    assert fol(reduce_term("(1,)")) == fol(ctor("tuple", [num(1)]))
