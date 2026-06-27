from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import ArrayLiteral, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class ArrayLiteralSugar:
    node: ast.List

    @classmethod
    def from_node(cls, node: ast.AST) -> "ArrayLiteralSugar | None":
        if not isinstance(node, ast.List):
            return None
        if not all(
            isinstance(item, ast.Constant) and isinstance(item.value, int)
            for item in node.elts
        ):
            return None
        return cls(node)

    def desugar(self) -> Outcome:
        return Complete(
            ArrayLiteral(tuple(TermValue(item.value) for item in self.node.elts))
        )
