from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import OpaqueOpCallsite, TermValue
from sugar_lift_py_tests.ir import ctor, num, str_const
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
def test_opaque_operator_arithmetic_cites_coordinates(method, operator) -> None:
    from sugar_lift_py_tests.outcome.exit_set import sole_completed_value

    value = OpaqueOpCallsite("len", TermValue(9), computed=None)
    outcome = getattr(value, method)(TermValue(2), "t.py:1", None)
    # An opaque call result has no decided runtime type, so the operator's
    # dunder is selected by types nobody looked at: the success face is the
    # undecided result of THIS occurrence citing both coordinates, never the
    # integer operator folded over them, and the other face is the halt.
    assert sole_completed_value(outcome).to_term(owner="test") == ctor(
        "python:binary_result",
        [
            str_const(operator),
            ctor("call:len", [num(9)]),
            num(2),
            str_const("t.py:1"),
        ],
    )
    (halt,) = outcome.halts()
    assert halt.effect.producer_node_owner == f"UndecidedBinary:{operator}"


def test_opaque_operator_unary_minus_is_the_undecided_two_faces() -> None:
    """An opaque call result has no decided runtime type for unary ``-``:
    the one undecided unary, its completed face the result of THIS
    occurrence over the coordinate, its other face the halt (#7757 NEW-8)."""
    from sugar_lift_py_tests.outcome.exit_set import sole_completed_value

    value = OpaqueOpCallsite("len", TermValue(9), computed=None)
    outcome = value.unary_minus("t.py:1")

    assert sole_completed_value(outcome).to_term(owner="test") == ctor(
        "python:unary_result",
        [str_const("-"), ctor("call:len", [num(9)]), str_const("t.py:1")],
    )
    (halt,) = outcome.halts()
    assert halt.effect.producer_node_owner == "SymbolicValue.unary_minus"


@pytest.mark.parametrize(("method", "operator"), (("multiply", "*"), ("power", "**")))
def test_a_coordinate_spelled_len_gets_no_builtin_len_warrant(method, operator) -> None:
    """``TermValue`` once read ``callee == "len"`` as the builtin's integer
    result contract.  No minting site decides a coordinate is the builtin
    ``len`` (#7757), so a coordinate merely spelled ``len`` -- a rebound
    ``len`` spells the same -- is never folded into ``2 * call:len(...)``."""
    from sugar_lift_py_tests.outcome import Completed

    spelled = OpaqueOpCallsite("len", TermValue(9), computed=None)
    warranted = ctor(operator, [num(2), ctor("call:len", [num(9)])])
    try:
        outcome = getattr(TermValue(2), method)(spelled, "t.py:1", None)
    except SugarNotWritten:
        return  # refused by name
    for face in outcome.exits:
        if isinstance(face, Completed):
            assert face.value.to_term(owner="test") != warranted


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
