from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import CallSiteValue, ListValue, TermValue
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.iterator_value import ListIteratorValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.operations.iterator_operation import IteratorOperation
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass
class _ProducerCompletion(ConstructedTermSugar):
    value: object
    reductions: int = 0

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        self.reductions += 1
        return Complete(self.value)

    def to_term(self, *, owner: str):
        del owner
        return ctor("test:call-iterable-producer", ())


def _call(body, *, target_name="source_iterable") -> CallSiteValue:
    return CallSiteValue(
        target_name=target_name,
        arg_values=(),
        parameters=(),
        term=ctor(f"call:{target_name}", ()),
        body=None if body is None else SugarBody(body, SugarRole.CONTROL_FLOW_BODY),
        site="producer.py:4:8",
    )


def _iterate(call: CallSiteValue):
    return IteratorOperation(owner="test", blame="loop.py:8:4").submit(call, None)


def test_call_iterates_the_authenticated_source_return_exactly_once() -> None:
    body = _ProducerCompletion(ListValue((TermValue(1), TermValue(2))))

    outcome = _iterate(_call(body))

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ListIteratorValue)
    assert outcome.value.elements == (TermValue(1), TermValue(2))
    assert body.reductions == 1


def test_retained_call_iterates_without_replaying_its_producer() -> None:
    body = _ProducerCompletion(ListValue((TermValue(3),)))
    produced = _call(body).producer_outcome(None)
    assert isinstance(produced, Complete)

    outcome = _iterate(produced.value)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ListIteratorValue)
    assert outcome.value.elements == (TermValue(3),)
    assert body.reductions == 1


def test_bodyless_call_named_like_a_list_stays_loud() -> None:
    with pytest.raises(ConstructionPanic, match="iter_with"):
        _iterate(_call(None, target_name="list"))


def test_ambiguous_source_returns_do_not_choose_an_iterable_face() -> None:
    ambiguous = BlockValue(
        (
            ReturnValue(ListValue((TermValue(1),))),
            ReturnValue(ListValue((TermValue(2),))),
        ),
        can_fall_through=False,
    )
    body = _ProducerCompletion(ambiguous)

    with pytest.raises(ConstructionPanic, match="iter_with"):
        _iterate(_call(body))

    assert body.reductions == 1
