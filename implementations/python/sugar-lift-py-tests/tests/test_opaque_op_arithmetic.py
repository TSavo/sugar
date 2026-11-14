from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import OpaqueOpCallsite, TermValue
from sugar_lift_py_tests.ir import ctor, num
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
    value = OpaqueOpCallsite("len", TermValue(9), computed=None)
    outcome = getattr(value, method)(TermValue(2), "t.py:1", None)
    assert outcome.value.to_term(owner="test") == ctor(
        operator, [ctor("call:len", [num(9)]), num(2)]
    )


def test_opaque_operator_unary_minus_is_named_refusal() -> None:
    """An opaque call result has no decided runtime type for unary ``-``."""
    value = OpaqueOpCallsite("len", TermValue(9), computed=None)
    with pytest.raises(SugarNotWritten) as raised:
        value.unary_minus("t.py:1")

    assert raised.value.owner == "unary_operation_exception_floor"
    assert raised.value.observed == "SymbolicValue -"


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
