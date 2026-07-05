from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import typed_red_effect_witness
from sugar_lift_py_tests.sugar.witnesses import SugarRedEffectWitnessPair


@dataclass(frozen=True)
class StarredSugar(Sugar, role=SugarRole.TERM):
    blame: str
    operand_observed: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Starred"

    @classmethod
    def witnesses(cls) -> SugarRedEffectWitnessPair:
        return typed_red_effect_witness(
            name="starred_runtime_effect",
            owner_sugar=cls.__name__,
            source="def A(xs):\n    return [*xs]\n",
            effect_class="RuntimeEffect",
            reason_needle="starred expression runtime boundary",
            blame_needle="test_witness.py:2:12",
            wrong_reason_needle="boolean expression runtime boundary",
        )

    @classmethod
    def build(cls, site, ctx) -> "StarredSugar":
        del ctx
        if not cls.owns(site):
            raise TypeError("StarredSugar claim built a non-Starred")
        terms = site.terms()
        operand = terms[0].observed if terms else "<missing>"
        return cls(blame=site.blame, operand_observed=operand)

    def desugar(self, ctx) -> Outcome:
        del ctx
        return _runtime_expansion_effect(self.blame, self.operand_observed)


def _runtime_expansion_effect(blame: str, operand_observed: str) -> Incomplete:
    return Incomplete(
        RuntimeEffect(
            "starred expression runtime boundary: "
            f"operand `{operand_observed}` must be iterated at runtime before "
            "call or display construction. Python evaluates this at runtime; "
            "keep as typed red until a narrower vendor-cited reduction owns "
            f"the shape. blame={blame}"
        )
    )
