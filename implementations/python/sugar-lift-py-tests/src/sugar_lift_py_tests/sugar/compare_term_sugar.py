from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import (
    EffectWitnessSource,
    SugarRedEffectWitnessPair,
    TypedRedEffectExpectation,
)

_VALUE_POSITION_OPERATORS = frozenset({"In", "NotIn", "Is", "IsNot"})


@dataclass(frozen=True)
class CompareTermSugar(Sugar, role=SugarRole.TERM):
    operator: str
    left_observed: str
    right_observed: str
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Compare":
            return False
        operators = site.compare_ops()
        comparators = site.compare_comparators()
        return (
            len(operators) == 1
            and len(comparators) == 1
            and operators[0] in _VALUE_POSITION_OPERATORS
        )

    @classmethod
    def build(cls, site, ctx) -> "CompareTermSugar":
        del ctx
        if not cls.owns(site):
            raise TypeError("CompareTermSugar claim built an unsupported comparison")
        return cls(
            operator=site.compare_ops()[0],
            left_observed=site.compare_left().observed,
            right_observed=site.compare_comparators()[0].observed,
            blame=site.blame,
        )

    @classmethod
    def witnesses(cls) -> SugarRedEffectWitnessPair:
        return SugarRedEffectWitnessPair(
            name="value_position_compare_runtime_effect",
            owner_sugar=cls.__name__,
            family="typed-red-effect",
            truthful=EffectWitnessSource(
                source=(
                    "def A(module_name):\n"
                    "    return module_name not in ['pandas', 'pandas.testing']\n"
                ),
                expectation=TypedRedEffectExpectation(
                    effect_class="RuntimeEffect",
                    reason_needle="value-position comparison runtime boundary",
                    blame_needle="test_witness.py:2:11",
                ),
                expected_match=True,
            ),
            lying=EffectWitnessSource(
                source=(
                    "def A(module_name):\n"
                    "    return module_name not in ['pandas', 'pandas.testing']\n"
                ),
                expectation=TypedRedEffectExpectation(
                    effect_class="RuntimeEffect",
                    reason_needle="generator expression runtime boundary",
                    blame_needle="test_witness.py:2:11",
                ),
                expected_match=False,
            ),
        )

    def _build(self, ctx) -> Outcome:
        del ctx
        return Incomplete(
            RuntimeEffect(
                "value-position comparison runtime boundary: "
                "crime=term Compare used as a value; "
                "owner=CompareTermSugar; "
                f"shape=operator `{self.operator}` left `{self.left_observed}` "
                f"right `{self.right_observed}`; "
                "replacement=use the assertion-position membership/identity sugar "
                "when this is a claim, or add a cited value-position boolean floor "
                "before treating it as green; "
                f"blame={self.blame}"
            )
        )
