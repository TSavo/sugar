from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import inert_statement_return_witness
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing, SugarWitnessPair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ExprSugar(Sugar, role=SugarRole.STATEMENT):
    """An expression statement. It reduces its value; the value owns the statement
    face (ordinary values discard to support; a ScopeRebind keeps itself so the
    block threads the rebind). Incomplete still propagates (a halt is not discarded)."""

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
        # Reduce the value; the value owns the statement face -- ordinary values
        # discard to SupportValue, a ScopeRebind keeps itself so the block threads
        # the rebind (contribution still empty).
        return self.value.reduce(ctx).and_then(
            lambda value: value.as_expression_statement()
        )

