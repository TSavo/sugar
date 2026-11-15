from __future__ import annotations

from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.ir import ctor, num


def test_callsite_left_shift_is_the_two_faced_undecided_binary() -> None:
    """A call result's type is undecided, so ``decode() << 8`` may raise.

    The one undecided-binary law answers it: the undecided
    ``python:binary_result`` under the operation's ``completes`` atom, and an
    undetermined halt under the complement. No ``<<`` coordinate is folded
    over the call, and no sole completion drops the raise.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.outcome.exit_set import (
        Completed,
        Halted,
        complement_guard,
    )

    receiver = CallSiteValue(
        target_name="decode",
        arg_values=(),
        parameters=(),
        term=ctor("call:decode", []),
        body=None,
    )
    outcome = receiver.left_shift(TermValue(8), "state.py:1", None)

    (done,) = [face for face in outcome.exits if isinstance(face, Completed)]
    (halt,) = [face for face in outcome.exits if isinstance(face, Halted)]
    assert "python:binary_op.completes" in repr(done.guard)
    assert halt.guard == complement_guard(done.guard)
    assert isinstance(done.value, SymbolicValue)
    assert done.value.term.name == "python:binary_result"
    assert done.value.term.args[0].value == "<<"
    assert done.value.term != ctor("<<", [ctor("call:decode", []), num(8)])
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.producer_node_owner == "UndecidedBinary:<<"


def test_callsite_declares_its_left_shift_floor_structurally() -> None:
    assert "left_shift" in CallSiteValue.__dict__
