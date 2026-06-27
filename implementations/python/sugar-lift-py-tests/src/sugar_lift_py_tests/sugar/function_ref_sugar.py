from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import FunctionCallable
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class FunctionRefSugar:
    name: str
    parameter: str
    return_name: str

    @classmethod
    def from_site(
        cls,
        site,
        *,
        functions_by_name: dict[str, ast.FunctionDef],
    ) -> "FunctionRefSugar | None":
        return function_ref_sugar(site.node, functions_by_name)

    def desugar(self) -> Outcome:
        return Complete(
            FunctionCallable(
                name=self.name,
                parameter=self.parameter,
                return_name=self.return_name,
            )
        )


def function_ref_sugar(
    node: ast.AST,
    functions_by_name: dict[str, ast.FunctionDef],
) -> FunctionRefSugar | None:
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
    return FunctionRefSugar(
        name=function.name,
        parameter=parameter,
        return_name=body.value.id,
    )
