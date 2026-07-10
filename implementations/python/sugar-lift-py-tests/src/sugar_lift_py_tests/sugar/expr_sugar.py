from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import SupportValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import inert_statement_return_witness
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing, SugarWitnessPair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ExprSugar(Sugar, role=SugarRole.STATEMENT):
    """An expression statement. It reduces its value and discards it: the statement
    is support. Incomplete still propagates (a halt is not discarded)."""

    value: SugarBody

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Expr"

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
        # Reduce the value, discard it: the statement is support.
        return self.value.reduce(ctx).and_then(lambda value: Complete(SupportValue()))
