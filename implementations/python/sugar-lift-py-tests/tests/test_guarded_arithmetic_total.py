from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import GuardedValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import atomic, ctor, make_var, num


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
def test_guarded_arithmetic_distributes_to_both_faces(method, operator) -> None:
    guard = atomic("choose", [])
    value = GuardedValue(
        guard,
        SymbolicValue(make_var("left")),
        SymbolicValue(make_var("right")),
    )
    outcome = getattr(value, method)(TermValue(2), "t.py:1")

    assert outcome.value == GuardedValue(
        guard,
        SymbolicValue(ctor(operator, [make_var("left"), num(2)])),
        SymbolicValue(ctor(operator, [make_var("right"), num(2)])),
    )


def test_guarded_unary_minus_distributes_to_both_faces() -> None:
    guard = atomic("choose", [])
    value = GuardedValue(
        guard,
        SymbolicValue(make_var("left")),
        SymbolicValue(make_var("right")),
    )
    outcome = value.unary_minus("t.py:1")
    assert outcome.value == GuardedValue(
        guard,
        SymbolicValue(ctor("py.neg", [make_var("left")])),
        SymbolicValue(ctor("py.neg", [make_var("right")])),
    )


def test_guarded_value_declares_full_arithmetic_surface() -> None:
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
    assert expected <= GuardedValue.__dict__.keys()
