from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import OpaqueOpCallsite, TermValue
from sugar_lift_py_tests.ir import ctor, num


@pytest.mark.parametrize(
    ("method", "operator"),
    (
        ("add", "+"),
        ("subtract", "-"),
        ("multiply", "*"),
        ("divide", "/"),
        ("floor_divide", "//"),
        ("modulo", "%"),
        ("left_shift", "<<"),
        ("right_shift", ">>"),
    ),
)
def test_opaque_operator_arithmetic_cites_coordinates(method, operator) -> None:
    value = OpaqueOpCallsite("len", TermValue(9), computed=None)
    outcome = getattr(value, method)(TermValue(2), "t.py:1")
    assert outcome.value.to_term(owner="test") == ctor(
        operator, [ctor("call:len", [num(9)]), num(2)]
    )


def test_opaque_operator_unary_minus_cites_coordinate() -> None:
    value = OpaqueOpCallsite("len", TermValue(9), computed=None)
    outcome = value.unary_minus("t.py:1")
    assert outcome.value.to_term(owner="test") == ctor(
        "py.neg", [ctor("call:len", [num(9)])]
    )


def test_opaque_operator_declares_full_arithmetic_surface() -> None:
    expected = {
        "add",
        "subtract",
        "multiply",
        "divide",
        "floor_divide",
        "modulo",
        "left_shift",
        "right_shift",
        "unary_minus",
    }
    assert expected <= OpaqueOpCallsite.__dict__.keys()
