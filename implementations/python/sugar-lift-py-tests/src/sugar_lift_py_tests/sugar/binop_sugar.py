from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.operations import BinaryOperatorOperation, perform_operation
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody

_SYMBOL: dict[str, str] = {
    "Add": "+",
    "Sub": "-",
    "Mult": "*",
    "Div": "/",
    "FloorDiv": "//",
    "Mod": "%",
    "Pow": "**",
}


@dataclass(frozen=True)
class BinOpSugar(Sugar, role=SugarRole.TERM):
    operator: str
    left: SugarBody
    right: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "BinOp" and site.operator_kind() in _SYMBOL

    @classmethod
    def build(cls, site, ctx) -> "BinOpSugar":
        sugar = cls.from_site(
            site,
            left=ctx.build_body(site.binop_left(), SugarRole.TERM),
            right=ctx.build_body(site.binop_right(), SugarRole.TERM),
        )
        if sugar is None:
            raise TypeError("BinOpSugar claim built a non-arithmetic binop")
        return sugar

    @classmethod
    def from_site(
        cls, site, *, left: SugarBody, right: SugarBody
    ) -> "BinOpSugar | None":
        if site.observed != "BinOp" or site.operator_kind() not in _SYMBOL:
            return None
        return cls(
            operator=_SYMBOL[site.operator_kind()],
            left=left,
            right=right,
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        # match each operand: an Incomplete (a runtime effect) bubbles upward unchanged.
        left_outcome = self.left.reduce(ctx)
        if isinstance(left_outcome, Incomplete):
            return left_outcome
        right_outcome = self.right.reduce(ctx)
        if isinstance(right_outcome, Incomplete):
            return right_outcome
        left = complete_value(left_outcome, owner="BinOpSugar left")
        right = complete_value(right_outcome, owner="BinOpSugar right")
        return perform_operation(
            owner="BinOpSugar",
            blame=self.blame,
            receiver=left,
            method_name="binary_operator_with",
            operation=BinaryOperatorOperation(
                operator=self.operator,
                right=right,
                owner="BinOpSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402

BINOP_CLAIM = next(c for c in _rc() if c.name == "BinOpSugar")
