from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_bitwise_op_sugar
from sugar_lift_py_tests.floor import TermValue
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
        left = _term_value(
            complete_value(self.left.reduce(ctx), owner="BitwiseOpSugar left")
        )
        right = _term_value(
            complete_value(self.right.reduce(ctx), owner="BitwiseOpSugar right")
        )
        if self.operator == "&":
            return Complete(TermValue(left.value & right.value))
        if self.operator == "<<":
            return Complete(TermValue(left.value << right.value))
        raise TypeError(f"write more Sugar for bitwise operator `{self.operator}`")


def _operator(op: ast.operator) -> str | None:
    if isinstance(op, ast.BitAnd):
        return "&"
    if isinstance(op, ast.LShift):
        return "<<"
    return None


def _term_value(value) -> TermValue:
    if not isinstance(value, TermValue):
        raise TypeError("BitwiseOpSugar operands must desugar to TermValue")
    return value


def _owns(site) -> bool:
    return isinstance(site.node, ast.BinOp) and _operator(site.node.op) is not None


BITWISE_OP_CLAIM = SugarClaim(
    name="BitwiseOpSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=build_bitwise_op_sugar,
)
