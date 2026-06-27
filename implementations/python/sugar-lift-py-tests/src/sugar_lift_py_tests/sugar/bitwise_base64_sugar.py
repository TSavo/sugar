from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class BitwiseBase64Sugar:
    stmt: ast.Return

    @classmethod
    def from_stmt(cls, stmt: ast.stmt) -> "BitwiseBase64Sugar | None":
        if not isinstance(stmt, ast.Return) or stmt.value is None:
            return None
        try:
            _validate_expr(stmt.value)
        except ValueError:
            return None
        return cls(stmt=stmt)

    def apply(self, env: dict[str, int | str]) -> Outcome:
        return Complete(StringValue(str(_eval_expr(self.stmt.value, env))))


def _validate_expr(node: ast.AST) -> None:
    if isinstance(node, ast.BinOp):
        if not isinstance(
            node.op,
            (ast.Add, ast.BitAnd, ast.BitOr, ast.LShift, ast.RShift),
        ):
            raise ValueError("unsupported base64 binary op")
        _validate_expr(node.left)
        _validate_expr(node.right)
        return
    if isinstance(node, ast.Subscript):
        _validate_expr(node.value)
        _validate_expr(node.slice)
        return
    if isinstance(node, ast.Name):
        return
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return
    raise ValueError(f"unsupported base64 expression: {type(node).__name__}")


def _eval_expr(node: ast.AST, env: dict[str, int | str]) -> int | str:
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Subscript):
        receiver = _eval_expr(node.value, env)
        index = _eval_expr(node.slice, env)
        if not isinstance(receiver, str) or not isinstance(index, int):
            raise ValueError("base64 subscript requires string receiver and int index")
        return receiver[index]
    if isinstance(node, ast.BinOp):
        left = _eval_expr(node.left, env)
        right = _eval_expr(node.right, env)
        if isinstance(node.op, ast.Add):
            return left + right
        if not isinstance(left, int) or not isinstance(right, int):
            raise ValueError("base64 bitwise operands must be integers")
        if isinstance(node.op, ast.BitAnd):
            return left & right
        if isinstance(node.op, ast.BitOr):
            return left | right
        if isinstance(node.op, ast.LShift):
            return left << right
        if isinstance(node.op, ast.RShift):
            return left >> right
    raise ValueError(f"unsupported base64 expression: {type(node).__name__}")
