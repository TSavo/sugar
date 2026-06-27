from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Protocol

from sugar_lift_py_tests.bitvector_solver import solve_bitvector_binary
from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import Complete, Outcome


class Base64Expr(Protocol):
    def evaluate(self, env: dict[str, int | str]) -> int | str: ...


@dataclass(frozen=True)
class NameExpr:
    name: str

    def evaluate(self, env: dict[str, int | str]) -> int | str:
        return env[self.name]


@dataclass(frozen=True)
class IntExpr:
    value: int

    def evaluate(self, _env: dict[str, int | str]) -> int:
        return self.value


@dataclass(frozen=True)
class SubscriptExpr:
    receiver: Base64Expr
    index: Base64Expr

    def evaluate(self, env: dict[str, int | str]) -> str:
        receiver = self.receiver.evaluate(env)
        index = self.index.evaluate(env)
        if not isinstance(receiver, str) or not isinstance(index, int):
            raise ValueError("base64 subscript requires string receiver and int index")
        return receiver[index]


@dataclass(frozen=True)
class BinaryExpr:
    operator: str
    left: Base64Expr
    right: Base64Expr

    def evaluate(self, env: dict[str, int | str]) -> int | str:
        left = self.left.evaluate(env)
        right = self.right.evaluate(env)
        if self.operator == "+":
            return _add(left, right)
        if not isinstance(left, int) or not isinstance(right, int):
            raise ValueError("base64 bitvector operands must be integers")
        return solve_bitvector_binary(self.operator, left, right)


@dataclass(frozen=True)
class BitwiseBase64Sugar:
    expression: Base64Expr

    @classmethod
    def from_site(cls, site, _ctx=None) -> "BitwiseBase64Sugar | None":
        stmt = site.node
        if not isinstance(stmt, ast.Return) or stmt.value is None:
            return None
        try:
            expression = _lower_expr(stmt.value)
        except ValueError:
            return None
        return cls(expression=expression)

    def apply(self, env: dict[str, int | str]) -> Outcome:
        return Complete(StringValue(str(self.expression.evaluate(env))))


def _lower_expr(node: ast.AST) -> Base64Expr:
    if isinstance(node, ast.BinOp):
        operator = _operator(node.op)
        if operator is None:
            raise ValueError("unsupported base64 binary op")
        return BinaryExpr(
            operator=operator,
            left=_lower_expr(node.left),
            right=_lower_expr(node.right),
        )
    if isinstance(node, ast.Subscript):
        return SubscriptExpr(
            receiver=_lower_expr(node.value),
            index=_lower_expr(node.slice),
        )
    if isinstance(node, ast.Name):
        return NameExpr(node.id)
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return IntExpr(node.value)
    raise ValueError(f"unsupported base64 expression: {type(node).__name__}")


def _operator(op: ast.operator) -> str | None:
    if isinstance(op, ast.Add):
        return "+"
    if isinstance(op, ast.BitAnd):
        return "&"
    if isinstance(op, ast.BitOr):
        return "|"
    if isinstance(op, ast.LShift):
        return "<<"
    if isinstance(op, ast.RShift):
        return ">>"
    return None


def _add(left: int | str, right: int | str) -> int | str:
    if isinstance(left, str) and isinstance(right, str):
        return left + right
    if isinstance(left, int) and isinstance(right, int):
        return left + right
    raise ValueError("base64 addition requires matching operand types")
