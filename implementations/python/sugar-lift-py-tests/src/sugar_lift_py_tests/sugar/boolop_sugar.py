from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import typed_red_effect_witness
from sugar_lift_py_tests.sugar.witnesses import SugarRedEffectWitnessPair


@dataclass(frozen=True)
class BoolOpSugar(Sugar, role=SugarRole.TERM):
    operator: str
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "BoolOp"

    @classmethod
    def witnesses(cls) -> SugarRedEffectWitnessPair:
        return typed_red_effect_witness(
            name="boolop_runtime_effect",
            owner_sugar=cls.__name__,
            source="def A(z):\n    return z and 2\n",
            effect_class="RuntimeEffect",
            reason_needle="boolean expression runtime boundary",
            blame_needle="test_witness.py:2:11",
            wrong_reason_needle="starred expression runtime boundary",
        )

    @classmethod
    def build(cls, site, ctx) -> "BoolOpSugar":
        del ctx
        if not cls.owns(site):
            raise TypeError("BoolOpSugar claim built a non-boolop expression")
        return cls(operator=site.boolop_op_kind(), blame=site.blame)

    def desugar(self, ctx) -> Outcome:
        del ctx
        return Incomplete(
            RuntimeEffect(
                "boolean expression runtime boundary: Python short-circuits "
                f"`{self.operator}` and returns one of the original operand "
                "values, not a standalone boolean floor; keep as typed red until "
                f"truthiness/value-flow floors own this shape. blame={self.blame}"
            )
        )
