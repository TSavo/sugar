from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class StringLiteralSugar:
    node: ast.Constant

    @classmethod
    def from_node(cls, node: ast.AST) -> "StringLiteralSugar | None":
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            return None
        return cls(node)

    def desugar(self) -> Outcome:
        return Complete(StringValue(self.node.value))
