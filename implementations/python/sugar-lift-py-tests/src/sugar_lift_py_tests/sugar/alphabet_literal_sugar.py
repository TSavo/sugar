from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import Complete, Outcome

from .string_literal_sugar import StringLiteralSugar, string_literal_sugar


BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


@dataclass(frozen=True)
class AlphabetLiteralSugar:
    name: str
    literal: StringLiteralSugar

    @classmethod
    def from_site(cls, site, _ctx=None) -> "AlphabetLiteralSugar | None":
        stmt = site.node
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            return None
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            return None
        literal = string_literal_sugar(stmt.value)
        if literal is None or literal.value != BASE64_ALPHABET:
            return None
        return cls(name=target.id, literal=literal)

    def desugar(self) -> Outcome:
        return Complete(StringValue(self.literal.value))
