from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import Bv32Value, TermValue
from sugar_lift_py_tests.ir import Term, bvand, bvlshr, bvor, bvshl, num
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody

_BITWISE_OPS = {"BitAnd": "&", "BitOr": "|", "LShift": "<<", "RShift": ">>"}


@dataclass(frozen=True)
class BitwiseOpSugar(Sugar, role=SugarRole.TERM):
    operator: str
    left: SugarBody
    right: SugarBody

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
        )

    def desugar(self, ctx=None) -> Outcome:
        left = _bv32_term(complete_value(self.left.reduce(ctx), owner="BitwiseOpSugar left"))
        right = _bv32_term(complete_value(self.right.reduce(ctx), owner="BitwiseOpSugar right"))
        return Complete(Bv32Value(_bv32_binary(self.operator, left, right)))


def _bv32_term(value) -> Term:
    if isinstance(value, Bv32Value):
        return value.term
    if isinstance(value, TermValue):
        return num(value.value)
    raise TypeError(
        f"write more Floor for BitwiseOpSugar operand `{type(value).__name__}`: "
        "expected TermValue or Bv32Value"
    )


def _bv32_binary(operator: str, left: Term, right: Term) -> Term:
    if operator == "&":
        return bvand(left, right)
    if operator == "|":
        return bvor(left, right)
    if operator == "<<":
        return bvshl(left, right)
    if operator == ">>":
        return bvlshr(left, right)
    raise TypeError(f"write more Sugar for BitwiseOpSugar operator `{operator}`")


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402
BITWISE_OP_CLAIM = next(c for c in _rc() if c.name == "BitwiseOpSugar")
