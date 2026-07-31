"""A loop may iterate an authenticated sole return, never an opaque call result.

CPython 3.12.13 ``Lib/enum.py`` reaches this door at source bytes
``[19640, 19695]``: ``for key in ignore``.  The loop recurrence submits its
iterable to :class:`IteratorOperation`; the call-site producer, not the loop,
owns whether that result has an iterable Floor.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import CallSiteValue, FloorValue, ListValue, TermValue
from sugar_lift_py_tests.floor.iterator_value import ListIteratorValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.operations.iterator_operation import IteratorOperation
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass
class _SoleIterableReturn(ConstructedTermSugar):
    value: FloorValue

    @classmethod
    def witnesses(cls):
        return None

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)

    def to_term(self, *, owner: str):
        del owner
        return ctor("test:sole-iterable-return", ())


def _source_call_returning(value: FloorValue) -> CallSiteValue:
    call = CallSiteValue(
        target_name="enum_ignore_names",
        arg_values=(),
        parameters=(),
        term=ctor("call:enum_ignore_names", ()),
        body=SugarBody(_SoleIterableReturn(value), SugarRole.CONTROL_FLOW_BODY),
        site="Lib/enum.py:540:15",
        source_call_frame_cid="blake3-512:" + "7" * 128,
    )
    produced = call.producer_outcome(None)
    assert isinstance(produced, Complete)
    assert isinstance(produced.value, CallSiteValue)
    return produced.value


def test_loop_iterator_projects_authenticated_source_return() -> None:
    """Truthful arm: the retained list becomes the loop's exact iterator state."""
    values = (TermValue("left"), TermValue("right"))
    returned = _source_call_returning(ListValue(values))

    outcome = IteratorOperation(
        owner="LoopRecurrenceSugar", blame="Lib/enum.py:540:15"
    ).submit(returned, None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ListIteratorValue)
    assert outcome.value.elements == values
    assert outcome.value.index == 0


def test_loop_iterator_does_not_invent_iterability_for_bodyless_call() -> None:
    """Lying arm: a call without source-return testimony stays typed loud."""
    opaque = CallSiteValue(
        target_name="external_ignore_names",
        arg_values=(),
        parameters=(),
        term=ctor("call:external_ignore_names", ()),
        body=None,
        site="Lib/enum.py:540:15",
    )

    with pytest.raises(
        ConstructionPanic,
        match="observed=CallSiteValue requested=iter_with",
    ):
        IteratorOperation(
            owner="LoopRecurrenceSugar", blame="Lib/enum.py:540:15"
        ).submit(opaque, None)
