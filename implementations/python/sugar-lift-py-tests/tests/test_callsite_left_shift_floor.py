from __future__ import annotations

from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.ir import ctor, num


def test_callsite_left_shift_cites_the_opaque_operator_coordinate() -> None:
    receiver = CallSiteValue(
        target_name="decode",
        arg_values=(),
        parameters=(),
        term=ctor("call:decode", []),
        body=None,
    )
    outcome = receiver.left_shift(TermValue(8), "state.py:1")

    assert outcome.value.to_term(owner="test") == ctor(
        "<<", [ctor("call:decode", []), num(8)]
    )


def test_callsite_declares_its_left_shift_floor_structurally() -> None:
    assert "left_shift" in CallSiteValue.__dict__
