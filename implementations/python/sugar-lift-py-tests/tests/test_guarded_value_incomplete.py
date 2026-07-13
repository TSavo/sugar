from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import (
    ConditionalExpressionRuntimeEffect,
    RuntimeEffectWitness,
)
from sugar_lift_py_tests.floor import (
    FloorValue,
    GuardedValue,
    PredicateValue,
    StringValue,
)
from sugar_lift_py_tests.ir import _Connective, atomic
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


@dataclass(frozen=True)
class _EffectValue(FloorValue):
    @staticmethod
    def _effect(reason: str) -> ConditionalExpressionRuntimeEffect:
        operand = atomic("runtime-operand", [])
        return ConditionalExpressionRuntimeEffect(
            reason,
            witness=RuntimeEffectWitness(
                operation=operand,
                operand=operand,
                locus="t.py:1:0",
            ),
        )

    def add(self, other, site):
        del other, site
        return Incomplete(self._effect("guarded add effect"))

    def equals(self, other, site):
        del other, site
        return Incomplete(self._effect("guarded equals effect"))


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


def test_guarded_value_truth_joins_branch_booleans_under_the_guard() -> None:
    value = GuardedValue(
        atomic("guard", []),
        TrueBoolLiteralSugar(site="t.py:1:0"),
        FalseBoolLiteralSugar(site="t.py:1:0"),
    )

    outcome = value.truth("t.py:2:0")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, PredicateValue)
    assert isinstance(outcome.value.formula, _Connective)
    assert outcome.value.formula.kind == "and"
