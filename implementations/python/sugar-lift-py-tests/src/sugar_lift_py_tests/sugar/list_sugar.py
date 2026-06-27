from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.outcome import Outcome

from .map_builtin_sugar import MapBuiltinSugar


@dataclass(frozen=True)
class ListSugar:
    call: ast.Call
    body: MapBuiltinSugar

    @classmethod
    def from_call(
        cls,
        node: ast.AST,
        functions_by_name: dict[str, ast.FunctionDef],
        *,
        blame: str,
    ) -> "ListSugar | None":
        if not isinstance(node, ast.Call):
            return None
        if not isinstance(node.func, ast.Name) or node.func.id != "list":
            return None
        if node.keywords or len(node.args) != 1:
            return None
        body = MapBuiltinSugar.from_call(
            node.args[0],
            functions_by_name,
            blame=blame,
        )
        if body is None:
            return None
        return cls(call=node, body=body)

    def desugar(self) -> Outcome:
        return self.body.desugar()
