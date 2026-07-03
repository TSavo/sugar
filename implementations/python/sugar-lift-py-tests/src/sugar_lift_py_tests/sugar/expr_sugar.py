from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import SupportValue
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ExprSugar(Sugar, role=SugarRole.STATEMENT):
    value: SugarBody

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Expr":
            return False
        terms = site.terms()
        return not (
            len(terms) == 1
            and terms[0].observed == "PrimitiveLiteral"
            and isinstance(terms[0].literal_value(), str)
        )

    @classmethod
    def witnesses(cls) -> NotVerdictBearing:
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="SupportValue",
            reason="expression statements evaluate for effects and leave no FOL claim",
        )

    @classmethod
    def build(cls, site, ctx) -> "ExprSugar":
        if not cls.owns(site):
            raise TypeError("ExprSugar claim built a non-expression statement")
        return cls(value=ctx.build_body(site.expr_value(), SugarRole.TERM))

    def desugar(self, ctx) -> Outcome:
        outcome = self.value.reduce(ctx)
        if isinstance(outcome, Incomplete):
            return outcome
        return Complete(SupportValue())
