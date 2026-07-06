from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.operations import UnaryOperatorOperation, perform_operation
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import unary_op_return_witness
from sugar_lift_py_tests.sugar_body import SugarBody

_SYMBOL = {
    "UAdd": "py.pos",
    "USub": "py.neg",
    "Invert": "py.invert",
    "Not": "py.not",
}


@dataclass(frozen=True)
class UnaryOpSugar(Sugar, role=SugarRole.TERM):
    operator: str
    operand: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "UnaryOp" and site.operator_kind() in _SYMBOL

    @classmethod
    def build(cls, site, ctx) -> "UnaryOpSugar":
        sugar = cls.from_site(
            site,
            operand=ctx.build_body(site.unaryop_operand(), SugarRole.TERM),
        )
        if sugar is None:
            raise TypeError("UnaryOpSugar claim built an unsupported unary op")
        return sugar

    @classmethod
    def witnesses(cls):
        return unary_op_return_witness()

    @classmethod
    def from_site(cls, site, *, operand: SugarBody) -> "UnaryOpSugar | None":
        if site.observed != "UnaryOp" or site.operator_kind() not in _SYMBOL:
            return None
        return cls(
            operator=_SYMBOL[site.operator_kind()],
            operand=operand,
            blame=site.blame,
        )

    def _build(self, ctx) -> Outcome:
        operand_outcome = self.operand.reduce(ctx)
        if isinstance(operand_outcome, Incomplete):
            return operand_outcome
        operand = complete_value(operand_outcome, owner="UnaryOpSugar operand")
        if self.operator == "py.not":
            return Incomplete(
                RuntimeEffect(
                    "value-position unary not runtime boundary: "
                    "crime=UnaryOp Not requested as a term; "
                    "owner=UnaryOpSugar; "
                    f"shape=py.not({type(operand).__name__}); "
                    "replacement=use assertion-position NotSugar for claims, "
                    "or add a cited Python truthiness floor before treating "
                    "value-position not as green; "
                    f"blame={self.blame}"
                )
            )
        return perform_operation(
            owner="UnaryOpSugar",
            blame=self.blame,
            receiver=operand,
            operation=UnaryOperatorOperation(
                operator=self.operator,
                owner="UnaryOpSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )
