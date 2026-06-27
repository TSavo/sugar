from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import Complete, Outcome

from .string_literal_sugar import StringLiteralSugar


BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


@dataclass(frozen=True)
class AlphabetLiteralSugar:
    stmt: ast.Assign
    name: str
    literal: StringLiteralSugar

    @classmethod
    def from_stmt(cls, stmt: ast.stmt) -> "AlphabetLiteralSugar | None":
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            return None
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            return None
        literal = StringLiteralSugar.from_node(stmt.value)
        if literal is None or literal.node.value != BASE64_ALPHABET:
            return None
        return cls(stmt=stmt, name=target.id, literal=literal)

    def desugar(self) -> Outcome:
        return Complete(StringValue(self.literal.node.value))
