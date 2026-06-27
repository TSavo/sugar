from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, TypeAlias

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value

from .primitive_literal_sugar import PrimitiveLiteralSugar

BitwiseOperand: TypeAlias = Any


@dataclass(frozen=True)
class BitwiseOpSugar:
    node: ast.BinOp
    operator: str
    left: BitwiseOperand
    right: BitwiseOperand

    def __post_init__(self) -> None:
        if not isinstance(self.left, (PrimitiveLiteralSugar, BitwiseOpSugar)):
            raise TypeError("BitwiseOpSugar operands must be factory-built term sugar")
        if not isinstance(self.right, (PrimitiveLiteralSugar, BitwiseOpSugar)):
            raise TypeError("BitwiseOpSugar operands must be factory-built term sugar")

    @classmethod
    def from_site(cls, site, ctx) -> "BitwiseOpSugar | None":
        if not isinstance(site.node, ast.BinOp):
            return None
        operator = _operator(site.node.op)
        if operator is None:
            return None
        left = ctx.build_child(site.node.left, SugarRole.TERM).sugar
        right = ctx.build_child(site.node.right, SugarRole.TERM).sugar
        return cls(
            node=site.node,
            operator=operator,
            left=left,
            right=right,
        )

    def desugar(self) -> Outcome:
        left = _term_value(complete_value(self.left.desugar(), owner="BitwiseOpSugar left"))
        right = _term_value(complete_value(self.right.desugar(), owner="BitwiseOpSugar right"))
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


def _build(site, ctx) -> BitwiseOpSugar:
    sugar = BitwiseOpSugar.from_site(site, ctx)
    if sugar is None:
        raise TypeError("BitwiseOpSugar claim built a non-bitwise op")
    return sugar


BITWISE_OP_CLAIM = SugarClaim(
    name="BitwiseOpSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=_build,
)
