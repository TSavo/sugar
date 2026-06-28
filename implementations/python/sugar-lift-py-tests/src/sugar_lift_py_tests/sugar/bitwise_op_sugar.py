from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_bitwise_op_sugar
from sugar_lift_py_tests.floor import Bv32Value, TermValue
from sugar_lift_py_tests.ir import Term, bvand, bvlshr, bvor, bvshl, num
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BitwiseOpSugar:
    operator: str
    left: SugarBody
    right: SugarBody

    def __post_init__(self) -> None:
        if not isinstance(self.left, SugarBody):
            raise TypeError("BitwiseOpSugar operands must be factory-built bodies")
        if not isinstance(self.right, SugarBody):
            raise TypeError("BitwiseOpSugar operands must be factory-built bodies")

    @classmethod
    def from_site(
        cls, site, *, left: SugarBody, right: SugarBody
    ) -> "BitwiseOpSugar | None":
        if not isinstance(site.node, ast.BinOp):
            return None
        operator = _operator(site.node.op)
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


def _operator(op: ast.operator) -> str | None:
    if isinstance(op, ast.BitAnd):
        return "&"
    if isinstance(op, ast.BitOr):
        return "|"
    if isinstance(op, ast.LShift):
        return "<<"
    if isinstance(op, ast.RShift):
        return ">>"
    return None


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


def _owns(site) -> bool:
    return isinstance(site.node, ast.BinOp) and _operator(site.node.op) is not None


BITWISE_OP_CLAIM = SugarClaim(
    name="BitwiseOpSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=build_bitwise_op_sugar,
)
