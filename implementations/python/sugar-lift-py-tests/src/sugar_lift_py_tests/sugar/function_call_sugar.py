from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.ir import Formula, eq, make_var, str_const
from sugar_lift_py_tests.outcome import Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody

from .base64_body_sugar import Base64BodySugar

FunctionCallBody = SugarBody | Base64BodySugar


@dataclass(frozen=True)
class FunctionCallSugar:
    target_name: str
    argument: SugarBody
    body: FunctionCallBody

    def __post_init__(self) -> None:
        if not isinstance(self.argument, SugarBody):
            raise TypeError("FunctionCallSugar argument must be factory-built")
        if not isinstance(self.body, (SugarBody, Base64BodySugar)):
            raise TypeError("FunctionCallSugar body must be factory-built")

    @classmethod
    def from_site(
        cls,
        site,
        *,
        argument: SugarBody,
        body: FunctionCallBody,
    ) -> "FunctionCallSugar | None":
        node = site.node
        if not isinstance(node, ast.Call):
            return None
        if not isinstance(node.func, ast.Name):
            return None
        if node.keywords or len(node.args) != 1:
            return None
        return cls(
            target_name=node.func.id,
            argument=argument,
            body=body,
        )

    def desugar(self, ctx=None) -> Outcome:
        if isinstance(self.body, SugarBody):
            return self.body.reduce(ctx)
        argument = complete_value(
            self.argument.reduce(ctx),
            owner="FunctionCallSugar argument",
        )
        return self.body.apply(argument)

    def factory_steps(self, function: ast.FunctionDef) -> list[tuple[str, str, ast.stmt, str]]:
        if isinstance(self.body, SugarBody):
            return [("StringLiteralSugar", "Constant", function.body[0], "StringValue")]
        return self.body.factory_steps(function)

    def constraint_formulas(self, output: StringValue) -> list[Formula]:
        if isinstance(self.body, SugarBody):
            return [eq(make_var("out"), str_const(output.value))]
        argument = complete_value(
            self.argument.reduce(None),
            owner="FunctionCallSugar argument",
        )
        if not isinstance(argument, StringValue):
            raise ValueError("write more Floor for FunctionCallSugar argument")
        return self.body.constraint_formulas(argument, output)
