from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.ir import Formula, eq, make_var, str_const
from sugar_lift_py_tests.outcome import Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody

from .control_flow_body_sugar import ControlFlowBodySugar
from .generic_body_sugar import GenericBodySugar

FunctionCallBody = SugarBody | GenericBodySugar | ControlFlowBodySugar
_BODY_TYPES = (SugarBody, GenericBodySugar, ControlFlowBodySugar)


def callee_target(node: ast.Call) -> str | None:
    """The callee name of a call, whether bare (`f(...)`) or attribute
    (`np.rot90(...)`). The dig keys on this name and looks it up in the resolved
    function map -- so an imported `np.rot90` digs just like a local `f`."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


@dataclass(frozen=True)
class FunctionCallSugar:
    target_name: str
    argument: SugarBody
    body: FunctionCallBody

    def __post_init__(self) -> None:
        if not isinstance(self.argument, SugarBody):
            raise TypeError("FunctionCallSugar argument must be factory-built")
        if not isinstance(self.body, _BODY_TYPES):
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
        target = callee_target(node)
        if target is None:
            return None
        if node.keywords or len(node.args) != 1:
            return None
        return cls(
            target_name=target,
            argument=argument,
            body=body,
        )

    def desugar(self, ctx=None) -> Outcome:
        if isinstance(self.body, SugarBody):
            return self.body.reduce(ctx)
        raise TypeError(
            "FunctionCallSugar with GenericBodySugar lowers to ProofIR; call "
            "constraint_formulas instead of computing in Python"
        )

    def factory_steps(self, function: ast.FunctionDef) -> list[tuple[str, str, ast.stmt, str]]:
        if isinstance(self.body, SugarBody):
            return [("StringLiteralSugar", "Constant", function.body[0], "StringValue")]
        return self.body.factory_steps(function)

    def constraint_formulas(self, output: StringValue | None = None) -> list[Formula]:
        if isinstance(self.body, SugarBody):
            if output is None:
                raise ValueError("FunctionCallSugar simple body requires an output value")
            return [eq(make_var("out"), str_const(output.value))]
        return self.body.constraint_formulas()

    def constraint_formula_steps(self) -> list[Formula | None]:
        if isinstance(self.body, SugarBody):
            return []
        return self.body.constraint_formula_steps()

    def callsite_fact_formulas(self, expected: StringValue) -> list[Formula]:
        if isinstance(self.body, SugarBody):
            return [eq(make_var("out"), str_const(expected.value))]
        argument = complete_value(
            self.argument.reduce(None),
            owner="FunctionCallSugar argument",
        )
        if not isinstance(argument, StringValue):
            raise ValueError("write more Floor for FunctionCallSugar argument")
        return [
            eq(make_var(self.body.parameter), str_const(argument.value)),
            eq(make_var("out"), str_const(expected.value)),
        ]
