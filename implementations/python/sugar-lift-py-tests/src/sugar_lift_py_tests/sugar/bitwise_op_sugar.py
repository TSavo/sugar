from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.operations import BitwiseOperation, perform_operation
from sugar_lift_py_tests.outcome import Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody

_BITWISE_OPS = {"BitAnd": "&", "BitOr": "|", "LShift": "<<", "RShift": ">>"}


@dataclass(frozen=True)
class BitwiseOpSugar(Sugar, role=SugarRole.TERM):
    operator: str
    left: SugarBody
    right: SugarBody
    blame: str = "<unknown>"

    def __post_init__(self) -> None:
        if not isinstance(self.left, SugarBody):
            raise TypeError("BitwiseOpSugar operands must be factory-built bodies")
        if not isinstance(self.right, SugarBody):
            raise TypeError("BitwiseOpSugar operands must be factory-built bodies")

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "BinOp" and site.operator_kind() in _BITWISE_OPS

    @classmethod
    def build(cls, site, ctx) -> "BitwiseOpSugar":
        sugar = cls.from_site(
            site,
            left=ctx.build_body(site.binop_left(), SugarRole.TERM),
            right=ctx.build_body(site.binop_right(), SugarRole.TERM),
        )
        if sugar is None:
            raise TypeError("BitwiseOpSugar claim built a non-bitwise op")
        return sugar

    @classmethod
    def from_site(
        cls, site, *, left: SugarBody, right: SugarBody
    ) -> "BitwiseOpSugar | None":
        if site.observed != "BinOp":
            return None
        operator = _BITWISE_OPS.get(site.operator_kind())
        if operator is None:
            return None
        return cls(
            operator=operator,
            left=left,
            right=right,
            blame=site.blame,
        )

    def desugar(self, ctx=None) -> Outcome:
        left = complete_value(self.left.reduce(ctx), owner="BitwiseOpSugar left")
        right = complete_value(self.right.reduce(ctx), owner="BitwiseOpSugar right")
        return perform_operation(
            owner="BitwiseOpSugar",
            blame=self.blame,
            receiver=left,
            method_name="bitwise_with",
            operation=BitwiseOperation(
                operator=self.operator,
                operand=right,
                owner="BitwiseOpSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402

BITWISE_OP_CLAIM = next(c for c in _rc() if c.name == "BitwiseOpSugar")
