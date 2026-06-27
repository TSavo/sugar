from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.ir import Formula, eq, make_var, str_const
from sugar_lift_py_tests.outcome import Outcome, complete_value

from .base64_body_sugar import Base64BodySugar
from .string_literal_sugar import StringLiteralSugar, string_literal_sugar

FunctionCallBody = StringLiteralSugar | Base64BodySugar


@dataclass(frozen=True)
class FunctionCallSugar:
    call: ast.Call
    function: ast.FunctionDef
    argument: StringLiteralSugar
    body: FunctionCallBody

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
        argument = string_literal_sugar(node.args[0])
        if argument is None:
            return None
        body = _function_body_sugar(function)
        if body is None:
            return None
        return cls(
            call=node,
            function=function,
            argument=argument,
            body=body,
        )

    def desugar(self) -> Outcome:
        if isinstance(self.body, StringLiteralSugar):
            return self.body.desugar()
        argument = complete_value(self.argument.desugar(), owner="FunctionCallSugar argument")
        return self.body.apply(argument)

    def factory_steps(self) -> list[tuple[str, str, ast.stmt, str]]:
        if isinstance(self.body, StringLiteralSugar):
            return [("StringLiteralSugar", "Constant", self.function.body[0], "StringValue")]
        return self.body.factory_steps()

    def constraint_formulas(self, output: StringValue) -> list[Formula]:
        if isinstance(self.body, StringLiteralSugar):
            return [eq(make_var("out"), str_const(output.value))]
        argument = complete_value(self.argument.desugar(), owner="FunctionCallSugar argument")
        if not isinstance(argument, StringValue):
            raise ValueError("write more Floor for FunctionCallSugar argument")
        return self.body.constraint_formulas(argument, output)


def _function_body_sugar(function: ast.FunctionDef) -> FunctionCallBody | None:
    if len(function.body) == 1:
        body = function.body[0]
        if isinstance(body, ast.Return) and body.value is not None:
            return string_literal_sugar(body.value)
    return Base64BodySugar.from_function(function)
