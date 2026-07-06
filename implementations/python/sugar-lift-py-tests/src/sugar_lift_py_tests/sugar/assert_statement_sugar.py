from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import typed_red_effect_witness
from sugar_lift_py_tests.sugar.witnesses import SugarRedEffectWitnessPair


@dataclass(frozen=True)
class AssertStatementSugar(Sugar, role=SugarRole.STATEMENT):
    blame: str
    test_observed: str
    has_message: bool

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Assert"

    @classmethod
    def witnesses(cls) -> SugarRedEffectWitnessPair:
        return typed_red_effect_witness(
            name="assert_statement_runtime_effect",
            owner_sugar=cls.__name__,
            source=("def A(x):\n" "    assert x\n" "    return x\n"),
            effect_class="RuntimeEffect",
            reason_needle="assert statement runtime boundary",
            blame_needle="test_witness.py:2:4",
            wrong_reason_needle="named expression runtime boundary",
        )

    @classmethod
    def build(cls, site, ctx) -> "AssertStatementSugar":
        del ctx
        if not cls.owns(site):
            raise TypeError("AssertStatementSugar claim built a non-assert statement")
        return cls(
            blame=site.blame,
            test_observed=site.assert_test().observed,
            has_message=site.assert_has_message(),
        )

    def _build(self, ctx) -> Outcome:
        del ctx
        message_note = " with message" if self.has_message else ""
        return Incomplete(
            RuntimeEffect(
                "assert statement runtime boundary: "
                "crime=statement assert can raise AssertionError and is not a "
                "proof assertion at this statement-role boundary; "
                "owner=AssertStatementSugar; "
                f"shape=test `{self.test_observed}`{message_note}; "
                "replacement=route test-function assertions through assertion "
                "sugars, or keep runtime asserts as typed red effects; "
                f"blame={self.blame}"
            )
        )
