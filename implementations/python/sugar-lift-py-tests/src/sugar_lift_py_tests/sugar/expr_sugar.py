from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import SupportValue
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import inert_statement_return_witness
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing, SugarWitnessPair
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
    def new(cls, site, ctx) -> "ExprSugar":
        # An expression statement holds one expression, built through the factory.
        return cls(value=ctx.build_body(site.expr_value(), SugarRole.TERM))

    @classmethod
    def witnesses(cls) -> tuple[NotVerdictBearing, SugarWitnessPair]:
        return (
            NotVerdictBearing(
                sugar_name=cls.__name__,
                floor_name="SupportValue",
                reason="expression statements evaluate for effects and leave no FOL claim",
            ),
            inert_statement_return_witness(
                name="expr_support_return",
                owner_sugar=cls.__name__,
                statement="z",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # The statement's outcome is the expression's outcome -- reduce it.
        return self.value.reduce(ctx)

