from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import FunctionCallable
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class FunctionRefSugar:
    node: ast.Name
    function: ast.FunctionDef
    parameter: str
    return_name: str

    @classmethod
    def from_node(
        cls,
        node: ast.AST,
        functions_by_name: dict[str, ast.FunctionDef],
    ) -> "FunctionRefSugar | None":
        if not isinstance(node, ast.Name):
            return None
        function = functions_by_name.get(node.id)
        if function is None:
            return None
        if len(function.args.args) != 1 or len(function.body) != 1:
            return None
        body = function.body[0]
        if not isinstance(body, ast.Return) or not isinstance(body.value, ast.Name):
            return None
        parameter = function.args.args[0].arg
        return cls(
            node=node,
            function=function,
            parameter=parameter,
            return_name=body.value.id,
        )

    def desugar(self) -> Outcome:
        return Complete(
            FunctionCallable(
                name=self.function.name,
                parameter=self.parameter,
                return_name=self.return_name,
            )
        )
