from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.factory import SourceSite
from sugar_lift_py_tests.floor import StringValue, TermValue
from sugar_lift_py_tests.ir import Formula, eq, make_var, num, str_const
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value

from .alphabet_literal_sugar import AlphabetLiteralSugar
from .bitwise_base64_sugar import BitwiseBase64Sugar
from .ord_sugar import OrdSugar


@dataclass(frozen=True)
class Base64BodySugar:
    parameter: str
    alphabet: AlphabetLiteralSugar
    ords: tuple[OrdSugar, OrdSugar, OrdSugar]
    return_sugar: BitwiseBase64Sugar

    @classmethod
    def from_site(cls, site, _ctx=None) -> "Base64BodySugar | None":
        function = site.node
        if not isinstance(function, ast.FunctionDef):
            return None
        if len(function.args.args) != 1 or len(function.body) != 5:
            return None
        parameter = function.args.args[0].arg
        alphabet = AlphabetLiteralSugar.from_site(
            SourceSite.from_node(function.body[0], "<base64-body>")
        )
        if alphabet is None:
            return None
        ords = tuple(
            OrdSugar.from_site(
                SourceSite.from_node(stmt, "<base64-body>"),
                source_name=parameter,
            )
            for stmt in function.body[1:4]
        )
        if not all(ords):
            return None
        return_sugar = BitwiseBase64Sugar.from_site(
            SourceSite.from_node(function.body[4], "<base64-body>")
        )
        if return_sugar is None:
            return None
        return cls(
            parameter=parameter,
            alphabet=alphabet,
            ords=ords,  # type: ignore[arg-type]
            return_sugar=return_sugar,
        )

    def apply(self, argument: StringValue) -> Outcome:
        alphabet = complete_value(self.alphabet.desugar(), owner="Base64BodySugar alphabet")
        env: dict[str, int | str] = {
            self.parameter: argument.value,
            self.alphabet.name: alphabet.value,
        }
        for ord_sugar in self.ords:
            value = complete_value(
                ord_sugar.apply(argument),
                owner=f"Base64BodySugar {ord_sugar.target}",
            )
            if not isinstance(value, TermValue):
                raise ValueError(f"write more Floor for `{ord_sugar.target}`")
            env[ord_sugar.target] = value.value
        return self.return_sugar.apply(env)

    def factory_steps(self, function: ast.FunctionDef) -> list[tuple[str, str, ast.stmt, str]]:
        return [
            ("AlphabetLiteralSugar", "Assign", function.body[0], "StringValue"),
            *[
                ("OrdSugar", "Assign", stmt, "TermValue")
                for stmt in function.body[1:4]
            ],
            ("BitwiseBase64Sugar", "Return", function.body[4], "StringValue"),
        ]

    def constraint_formulas(self, argument: StringValue, output: StringValue) -> list[Formula]:
        alphabet = complete_value(self.alphabet.desugar(), owner="Base64BodySugar alphabet")
        return [
            eq(make_var(self.alphabet.name), str_const(alphabet.value)),
            *[
                eq(make_var(ord_sugar.target), num(ord(argument.value[ord_sugar.index])))
                for ord_sugar in self.ords
            ],
            eq(make_var("out"), str_const(output.value)),
        ]
