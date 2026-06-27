from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class StringLiteralSugar:
    value: str

    @classmethod
    def from_site(cls, site, _ctx=None) -> "StringLiteralSugar | None":
        value = string_literal_value(site.node)
        if value is None:
            return None
        return cls(value)

    def desugar(self) -> Outcome:
        return Complete(StringValue(self.value))


def string_literal_value(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None
    return node.value


def string_literal_sugar(node: ast.AST) -> StringLiteralSugar | None:
    value = string_literal_value(node)
    if value is None:
        return None
    return StringLiteralSugar(value)
