from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import ArrayLiteral, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class RangeSugar:
    call: ast.Call
    start: int
    stop: int

    @classmethod
    def from_call(cls, node: ast.AST) -> "RangeSugar | None":
        if not isinstance(node, ast.Call):
            return None
        if not isinstance(node.func, ast.Name) or node.func.id != "range":
            return None
        if node.keywords:
            return None
        if len(node.args) != 2:
            return None
        start = _int_constant(node.args[0])
        stop = _int_constant(node.args[1])
        if start is None or stop is None:
            return None
        return cls(call=node, start=start, stop=stop)

    def desugar(self) -> Outcome:
        return Complete(
            ArrayLiteral(tuple(TermValue(value) for value in range(self.start, self.stop)))
        )


def _int_constant(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None
