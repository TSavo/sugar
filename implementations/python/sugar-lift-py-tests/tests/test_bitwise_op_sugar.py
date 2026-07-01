"""BitwiseOpSugar reduces Python bit operators to the canonical bv32 ctors."""

from __future__ import annotations

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.floor import Bv32Value
from sugar_lift_py_tests.ir import ctor, make_var, num


def _x():
    return {"x": Bv32Value(make_var("x"))}


def test_bitwise_and_reduces_to_bv32_and():
    assert fol(reduce_term("x & 15", _x())) == fol(
        ctor("bv32.and", [make_var("x"), num(15)])
    )


def test_bitwise_rshift_reduces_to_bv32_lshr():
    assert fol(reduce_term("x >> 2", _x())) == fol(
        ctor("bv32.lshr", [make_var("x"), num(2)])
    )
