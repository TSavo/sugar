from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class MethodSugar:
    call: ast.Call
    receiver: ast.AST
    method_name: str
    args: tuple[ast.AST, ...]

    @classmethod
    def from_call(cls, node: ast.AST) -> "MethodSugar | None":
        if not isinstance(node, ast.Call):
            return None
        if not isinstance(node.func, ast.Attribute):
            return None
        return cls(
            call=node,
            receiver=node.func.value,
            method_name=node.func.attr,
            args=tuple(node.args),
        )
