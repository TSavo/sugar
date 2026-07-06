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


@dataclass(frozen=True)
class GeneratorExpSugar(Sugar, role=SugarRole.TERM):
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "GeneratorExp"

    @classmethod
    def build(cls, site, ctx) -> "GeneratorExpSugar":
        del ctx
        if site.observed != "GeneratorExp":
            raise TypeError("GeneratorExpSugar claim built a non-generator expression")
        return cls(blame=site.blame)

    @classmethod
    def witnesses(cls) -> SugarRedEffectWitnessPair:
        return SugarRedEffectWitnessPair(
            name="generator_expression_runtime_effect",
            owner_sugar=cls.__name__,
            family="typed-red-effect",
            truthful=EffectWitnessSource(
                source=(
                    "def A(axes):\n" "    return (x for x in [0, 1] if x not in axes)\n"
                ),
                expectation=TypedRedEffectExpectation(
                    effect_class="RuntimeEffect",
                    reason_needle="generator expression runtime boundary",
                    blame_needle="test_witness.py:2:11",
                ),
                expected_match=True,
            ),
            lying=EffectWitnessSource(
                source=(
                    "def A(axes):\n" "    return (x for x in [0, 1] if x not in axes)\n"
                ),
                expectation=TypedRedEffectExpectation(
                    effect_class="RuntimeEffect",
                    reason_needle="value-position comparison runtime boundary",
                    blame_needle="test_witness.py:2:11",
                ),
                expected_match=False,
            ),
        )

    def _build(self, ctx) -> Outcome:
        del ctx
        return Incomplete(
            RuntimeEffect(
                "generator expression runtime boundary: "
                "crime=lazy iterator requested as a term; "
                "owner=GeneratorExpSugar; "
                "shape=GeneratorExp; "
                "replacement=use finite comprehension sugar when a collection is "
                "materialized, or add a cited iterator/next floor before treating "
                "cursor-state as green; "
                f"blame={self.blame}"
            )
        )
