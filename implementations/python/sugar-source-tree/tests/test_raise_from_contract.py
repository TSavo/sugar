"""Red twins for the binary ``python:raise(exc, cause)`` contract."""

import tempfile
from dataclasses import dataclass, field

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.floor import CallSiteValue, NoneValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _raise(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    function = next(SourceFile(path_source(path)).functions())
    return next(node for node in function.walk() if node.kind == "Raise")


def _effect(source: str):
    outcome = _raise(source).sugar().desugar()
    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "RaiseEffect"
    return outcome.effect


def test_raise_from_constructs_exception_and_cause_on_the_halt_effect() -> None:
    effect = _effect(
        "def f():\n"
        "    raise ValueError('outer') from KeyError('inner')\n"
    )

    assert isinstance(effect.raised_value, CallSiteValue)
    assert effect.raised_value.target_name == "ValueError"
    assert isinstance(effect.cause_value, CallSiteValue)
    assert effect.cause_value.target_name == "KeyError"


def test_raise_without_from_carries_the_absent_cause_sentinel() -> None:
    effect = _effect("def f():\n    raise ValueError('outer')\n")

    assert effect.cause_value is None


def test_explicit_from_none_is_a_constructed_none_cause() -> None:
    effect = _effect("def f():\n    raise ValueError('outer') from None\n")

    assert isinstance(effect.cause_value, NoneValue)
    assert effect.cause_value is not None


def test_unwritten_cause_expression_stays_loud_at_the_cause() -> None:
    node = _raise(
        "async def f(cause):\n"
        "    raise ValueError('outer') from (await cause)\n"
    )

    with pytest.raises(SugarNotWritten, match=r"\[Await\.sugar\]"):
        node.sugar()


@dataclass(frozen=True)
class _RecordingSugar(Sugar):
    label: str
    events: list[str] = field(compare=False)
    value: int

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        self.events.append(self.label)
        return Complete(TermValue(self.value))


def test_exception_then_cause_each_desugar_exactly_once() -> None:
    events: list[str] = []
    site = _raise("def f():\n    raise ValueError()\n").fragment
    sugar = RaiseSugar(
        exception=_RecordingSugar("exception", events, 1),
        cause=_RecordingSugar("cause", events, 2),
        exception_name="ValueError",
        site=site,
    )

    outcome = sugar.desugar()

    assert isinstance(outcome, Incomplete)
    assert events == ["exception", "cause"]
    assert outcome.effect.raised_value == TermValue(1)
    assert outcome.effect.cause_value == TermValue(2)
