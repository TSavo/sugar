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
class NamedExprSugar(Sugar, role=SugarRole.TERM):
    target_name: str
    value_observed: str
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "NamedExpr"

    @classmethod
    def build(cls, site, ctx) -> "NamedExprSugar":
        del ctx
        if site.observed != "NamedExpr":
            raise TypeError("NamedExprSugar claim built a non-named expression")
        terms = site.terms()
        target = terms[0] if terms else None
        value = terms[1] if len(terms) > 1 else None
        target_name = (
            target.name_id()
            if target is not None and target.observed == "Name"
            else "<dynamic-target>"
        )
        return cls(
            target_name=target_name,
            value_observed=value.observed if value is not None else "<missing>",
            blame=site.blame,
        )

    @classmethod
    def witnesses(cls) -> SugarRedEffectWitnessPair:
        return SugarRedEffectWitnessPair(
            name="named_expr_runtime_effect",
            owner_sugar=cls.__name__,
            family="typed-red-effect",
            truthful=EffectWitnessSource(
                source=("def A(uuid4):\n" "    return [u := uuid4()]\n"),
                expectation=TypedRedEffectExpectation(
                    effect_class="RuntimeEffect",
                    reason_needle="named expression runtime boundary",
                    blame_needle="test_witness.py:2:12",
                ),
                expected_match=True,
            ),
            lying=EffectWitnessSource(
                source=("def A(uuid4):\n" "    return [u := uuid4()]\n"),
                expectation=TypedRedEffectExpectation(
                    effect_class="RuntimeEffect",
                    reason_needle="generator expression runtime boundary",
                    blame_needle="test_witness.py:2:12",
                ),
                expected_match=False,
            ),
        )

    def _build(self, ctx) -> Outcome:
        del ctx
        return Incomplete(
            RuntimeEffect(
                "named expression runtime boundary: "
                "crime=walrus binding requested as a term; "
                "owner=NamedExprSugar; "
                f"shape=NamedExpr target `{self.target_name}` value "
                f"`{self.value_observed}`; "
                "replacement=route through the alias/binding floor before the "
                "assigned value is used as green testimony; "
                f"blame={self.blame}"
            )
        )
