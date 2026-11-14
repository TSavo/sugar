"""A bodiless method call and a frameless spread call are the one unanswered call.

#7757 (found by #8043): ``dispatch_method_call`` completed outright when the
call had no site, and ``SpreadCallSugar`` either completed outright (no site)
or stated the unanswered call a second way (``python:spread_call.completes``,
owing nothing).  Both are now ``UnknownCalleeCallV1``: two faces, the raise
kept, and one unanswered call owed.  Neither ever completes alone.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.outcome.exit_set import Completed
from sugar_lift_py_tests.sugar.method_call_sugar import dispatch_method_call
from sugar_lift_py_tests.sugar.spread_sugar import SpreadCallSugar
from sugar_lift_py_tests.unanswered_calls import owed_calls


class _Site:
    """A fragment's two coordinates: its unit's source CID and its span."""

    class _Span:
        start_line, start_col, end_line, end_col = 4, 0, 4, 9

    source_cid = "blake3-512:" + "d" * 128
    line_col_span = _Span()


class _Operand:
    """One operand that reduces to a value no floor answers a method on."""

    def __init__(self, name: str) -> None:
        self.name = name

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(SymbolicValue(ctor(self.name, [])))


def _assert_one_unanswered_call(outcome, callee: str) -> None:
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == f"UnknownCallee:{callee}"
    assert "python:unknown_callee_call.completes" in str(completed[0].guard)
    assert len(owed_calls(outcome)) == 1


def test_an_unanswered_method_call_is_two_faced_and_owes_one_call() -> None:
    receiver = SymbolicValue(ctor("receiver", []))

    outcome = dispatch_method_call("foo", receiver, (), (), _Site(), None)

    _assert_one_unanswered_call(outcome, "foo")


def test_a_siteless_unanswered_method_call_never_completes() -> None:
    # The deleted guard completed it outright, dropping the raise.  Without a
    # source coordinate the unanswered call is refused by name, never total.
    receiver = SymbolicValue(ctor("receiver", []))

    with pytest.raises(ConstructionPanic):
        dispatch_method_call("foo", receiver, (), (), None, None)


def test_an_unanswered_spread_call_is_two_faced_and_owes_one_call() -> None:
    outcome = SpreadCallSugar(
        callee_name="f",
        callee=None,
        arguments=(("star", None, _Operand("a")),),
        site=_Site(),
    ).desugar(None)

    _assert_one_unanswered_call(outcome, "f")
    assert "python:spread_call" not in str(outcome.exits)


def test_a_siteless_unanswered_spread_call_never_completes() -> None:
    with pytest.raises(ConstructionPanic):
        SpreadCallSugar(
            callee_name="f",
            callee=None,
            arguments=(("star", None, _Operand("a")),),
            site=None,
        ).desugar(None)
