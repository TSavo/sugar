from __future__ import annotations

import pytest
from frame_fresh import fresh

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import GuardedValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted


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
    guard = atomic("choose", [])
    value = GuardedValue(
        guard,
        SymbolicValue(make_var("left")),
        SymbolicValue(make_var("right")),
    )
    outcome = getattr(value, method)(TermValue(2), "t.py:1", None)
    assert isinstance(outcome, ExitSet)
    halted = tuple(face for face in outcome.exits if isinstance(face, Halted))
    completed = tuple(face for face in outcome.exits if isinstance(face, Completed))
    # Each arm publishes Halted+Completed; normalize may merge same-effect
    # faces across arms under a disjoined guard.
    assert halted
    assert completed
    # An operand whose type is not decided names no exception: each arm's halt
    # is the undetermined raise of the one two-faced binary operation
    # (``undecided_binary_faces``), owned by its operator.
    assert all(
        type(face.effect) is UndeterminedRaiseEffect
        and face.effect.producer_node_owner == f"UndecidedBinary:{operator}"
        for face in halted
    )


def test_guarded_right_operand_preserves_both_dispatch_faces_on_each_branch() -> None:
    """The reflected guarded join conserves the same two producer faces."""
    guard = atomic("choose-right", [])
    right = GuardedValue(
        guard,
        SymbolicValue(make_var("right_true")),
        SymbolicValue(make_var("right_false")),
    )

    outcome = SymbolicValue(make_var("left")).subtract(right, "t.py:2", None)

    assert isinstance(outcome, ExitSet)
    assert {type(exit_).__name__ for exit_ in outcome.exits} == {
        "Completed",
        "Halted",
    }
    rendered = str(outcome)
    assert "right_true" in rendered
    assert "right_false" in rendered


def test_guarded_unary_minus_keeps_each_undecided_arm_two_faced() -> None:
    """A free symbol is an operand whose type is undecided, formal or not:
    each arm is the one undecided unary's two faces, its halt the
    undetermined raise owned by the operand's floor (#7757 NEW-8)."""
    guard = atomic("choose", [])
    value = GuardedValue(
        guard,
        SymbolicValue(make_var("left")),
        SymbolicValue(make_var("right")),
    )
    outcome = value.unary_minus("t.py:1")

    assert isinstance(outcome, ExitSet)
    halted = tuple(face for face in outcome.exits if isinstance(face, Halted))
    completed = tuple(face for face in outcome.exits if isinstance(face, Completed))
    assert halted
    assert completed
    assert all(
        type(face.effect) is UndeterminedRaiseEffect
        and face.effect.producer_node_owner == "SymbolicValue.unary_minus"
        for face in halted
    )
    assert all("python:unary_result" in repr(face.value) for face in completed)


def test_guarded_bitwise_or_distributes_exact_set_union_to_both_faces() -> None:
    from sugar_lift_py_tests.floor import SetValue

    guard = atomic("choose", [])
    value = GuardedValue(
        guard,
        fresh(SetValue, (TermValue(1),)),
        fresh(SetValue, (TermValue(2),)),
    )

    outcome = value.bitwise_or(
        fresh(SetValue, (TermValue(3),)),
        "t.py:1",
        None,
    )

    assert outcome == ExitSet.completed(
        GuardedValue(
            guard,
            fresh(SetValue, (TermValue(1), TermValue(3))),
            fresh(SetValue, (TermValue(2), TermValue(3))),
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
