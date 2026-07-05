from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import typed_red_effect_witness
from sugar_lift_py_tests.sugar.witnesses import SugarRedEffectWitnessPair


@dataclass(frozen=True)
class ForSugar(Sugar, role=SugarRole.STATEMENT):
    blame: str
    target_observed: str
    has_else: bool

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "For"

    @classmethod
    def witnesses(cls) -> SugarRedEffectWitnessPair:
        return typed_red_effect_witness(
            name="for_runtime_effect",
            owner_sugar=cls.__name__,
            source=(
                "def A(z):\n"
                "    x = 0\n"
                "    for item in [z, 2]:\n"
                "        x = item\n"
                "    return x\n"
            ),
            effect_class="RuntimeEffect",
            reason_needle="for loop runtime boundary",
            blame_needle="test_witness.py:3:4",
            wrong_reason_needle="boolean expression runtime boundary",
        )

    @classmethod
    def build(cls, site, ctx) -> "ForSugar":
        del ctx
        if not cls.owns(site):
            raise TypeError("ForSugar claim built a non-for statement")
        return cls(
            blame=site.blame,
            target_observed=site.for_target_observed(),
            has_else=site.for_orelse_count() != 0,
        )

    def _build(self, ctx) -> Outcome:
        del ctx
        else_note = " with else/fallthrough" if self.has_else else ""
        return Incomplete(
            RuntimeEffect(
                "for loop runtime boundary: Python evaluates iterator protocol, "
                f"target binding `{self.target_observed}`, loop body effects"
                f"{else_note}, and fallthrough at runtime; keep as typed red "
                "until iterator/body floors own this shape. "
                f"blame={self.blame}"
            )
        )
