from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.outcome import Outcome

from .string_literal_sugar import StringLiteralSugar


@dataclass(frozen=True)
class FunctionCallSugar:
    call: ast.Call
    function: ast.FunctionDef
    argument: StringLiteralSugar
    return_literal: StringLiteralSugar

    @classmethod
    def from_call(
        cls,
        node: ast.AST,
        functions_by_name: dict[str, ast.FunctionDef],
    ) -> "FunctionCallSugar | None":
        if not isinstance(node, ast.Call):
            return None
        if not isinstance(node.func, ast.Name):
            return None
        if node.keywords or len(node.args) != 1:
            return None
        function = functions_by_name.get(node.func.id)
        if function is None:
            return None
        argument = StringLiteralSugar.from_node(node.args[0])
        if argument is None:
            return None
        if len(function.body) != 1:
            return None
        body = function.body[0]
        if not isinstance(body, ast.Return) or body.value is None:
            return None
        return_literal = StringLiteralSugar.from_node(body.value)
        if return_literal is None:
            return None
        return cls(
            call=node,
            function=function,
            argument=argument,
            return_literal=return_literal,
        )

    def desugar(self) -> Outcome:
        return self.return_literal.desugar()
