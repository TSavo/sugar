from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import ConditionalExpressionRuntimeEffect
from sugar_lift_py_tests.floor import FloorValue, GuardedValue, StringValue
from sugar_lift_py_tests.ir import atomic
from sugar_lift_py_tests.outcome import Incomplete


@dataclass(frozen=True)
class _EffectValue(FloorValue):
    def add(self, other, site):
        del other, site
        return Incomplete(ConditionalExpressionRuntimeEffect("guarded add effect"))

    def equals(self, other, site):
        del other, site
        return Incomplete(ConditionalExpressionRuntimeEffect("guarded equals effect"))


def test_guarded_value_map_propagates_incomplete_without_force_complete() -> None:
    value = GuardedValue(atomic("guard", []), _EffectValue(), StringValue("ok"))

    outcome = value.add(StringValue("suffix"), "t.py:1:0")

    assert isinstance(outcome, Incomplete)
    assert "guarded add effect" in outcome.reason
    assert "effect occurs under branch condition" in outcome.reason


def test_guarded_value_predicate_propagates_incomplete_without_force_complete() -> None:
    value = GuardedValue(atomic("guard", []), StringValue("ok"), _EffectValue())

    outcome = value.equals(StringValue("expected"), "t.py:1:0")

    assert isinstance(outcome, Incomplete)
    assert "guarded equals effect" in outcome.reason
    assert "effect occurs under branch condition" in outcome.reason
