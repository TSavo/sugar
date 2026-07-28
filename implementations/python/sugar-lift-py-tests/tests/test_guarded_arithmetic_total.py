from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import GuardedValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.outcome import Complete, ExitSet
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
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
def test_guarded_arithmetic_preserves_undecided_arms_as_dual_edge_partitions(
    method, operator
) -> None:
    del operator
    guard = atomic("choose", [])
    value = GuardedValue(
        guard,
        SymbolicValue(make_var("left")),
        SymbolicValue(make_var("right")),
    )
    outcome = getattr(value, method)(TermValue(2), "t.py:1")
    assert isinstance(outcome, ExitSet)
    halted = tuple(face for face in outcome.exits if isinstance(face, Halted))
    completed = tuple(face for face in outcome.exits if isinstance(face, Completed))
    # Each arm publishes Halted+Completed; normalize may merge same-effect
    # faces across arms under a disjoined guard.
    assert halted
    assert completed
    assert all(
        isinstance(face.effect, RaiseEffect) and face.effect.producer_node_owner == "BinOp"
        for face in halted
    )


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
