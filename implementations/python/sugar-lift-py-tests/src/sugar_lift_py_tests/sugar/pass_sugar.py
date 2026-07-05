from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import SupportValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import inert_statement_return_witness
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing, SugarWitnessPair


@dataclass(frozen=True)
class PassSugar(Sugar, role=SugarRole.STATEMENT):
    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Pass"

    @classmethod
    def witnesses(cls) -> tuple[NotVerdictBearing, SugarWitnessPair]:
        return (
            NotVerdictBearing(
                sugar_name=cls.__name__,
                floor_name="SupportValue",
                reason="pass is inert control-flow support",
            ),
            inert_statement_return_witness(
                name="pass_support_return",
                owner_sugar=cls.__name__,
                statement="pass",
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "PassSugar":
        if not cls.owns(site):
            raise TypeError("PassSugar claim built a non-pass statement")
        return cls()

    def desugar(self, ctx=None) -> Outcome:
        return Complete(SupportValue())
