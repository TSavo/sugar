from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import GuardedValue, SymbolicValue, TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.panic import SugarNotWritten


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
def test_guarded_arithmetic_preserves_an_undecided_arm_as_a_named_refusal(
    method, operator
) -> None:
    guard = atomic("choose", [])
    value = GuardedValue(
        guard,
        SymbolicValue(make_var("left")),
        SymbolicValue(make_var("right")),
    )
    with pytest.raises(ConstructionPanic) as raised:
        getattr(value, method)(TermValue(2), "t.py:1")

    assert raised.value.info.owner == "binary_operation_exception_floor"
    assert raised.value.info.observed == f"SymbolicValue {operator} TermValue"


def test_guarded_unary_minus_preserves_an_undecided_arm_as_a_named_refusal() -> None:
    guard = atomic("choose", [])
    value = GuardedValue(
        guard,
        SymbolicValue(make_var("left")),
        SymbolicValue(make_var("right")),
    )
    with pytest.raises(SugarNotWritten) as raised:
        value.unary_minus("t.py:1")

    assert raised.value.owner == "unary_operation_exception_floor"
    assert raised.value.observed == "SymbolicValue -"


def test_guarded_bitwise_or_distributes_exact_set_union_to_both_faces() -> None:
    from sugar_lift_py_tests.floor import SetValue

    guard = atomic("choose", [])
    value = GuardedValue(
        guard,
        SetValue((TermValue(1),)),
        SetValue((TermValue(2),)),
    )

    outcome = value.bitwise_or(
        SetValue((TermValue(3),)),
        "t.py:1",
    )

    assert outcome == Complete(
        GuardedValue(
            guard,
            SetValue((TermValue(1), TermValue(3))),
            SetValue((TermValue(2), TermValue(3))),
        )
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
        "bitwise_or",
        "unary_minus",
    }
    assert expected <= GuardedValue.__dict__.keys()
