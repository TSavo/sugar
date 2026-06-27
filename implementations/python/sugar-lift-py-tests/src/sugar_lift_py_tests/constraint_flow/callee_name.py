from __future__ import annotations

import ast


def callee_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = callee_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""
