from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import StringValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value

from .alphabet_literal_sugar import AlphabetLiteralSugar
from .bitwise_base64_sugar import BitwiseBase64Sugar
from .ord_sugar import OrdSugar


@dataclass(frozen=True)
class Base64BodySugar:
    function: ast.FunctionDef
    parameter: str
    alphabet: AlphabetLiteralSugar
    ords: tuple[OrdSugar, OrdSugar, OrdSugar]
    return_sugar: BitwiseBase64Sugar

    @classmethod
    def from_function(cls, function: ast.FunctionDef) -> "Base64BodySugar | None":
        if len(function.args.args) != 1 or len(function.body) != 5:
            return None
        parameter = function.args.args[0].arg
        alphabet = AlphabetLiteralSugar.from_stmt(function.body[0])
        if alphabet is None:
            return None
        ords = tuple(
            OrdSugar.from_stmt(stmt, source_name=parameter)
            for stmt in function.body[1:4]
        )
        if not all(ords):
            return None
        return_sugar = BitwiseBase64Sugar.from_stmt(function.body[4])
        if return_sugar is None:
            return None
        return cls(
            function=function,
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

    def factory_steps(self) -> list[tuple[str, str, ast.stmt, str]]:
        return [
            ("AlphabetLiteralSugar", "Assign", self.alphabet.stmt, "StringValue"),
            *[
                ("OrdSugar", "Assign", ord_sugar.stmt, "TermValue")
                for ord_sugar in self.ords
            ],
            ("BitwiseBase64Sugar", "Return", self.return_sugar.stmt, "StringValue"),
        ]
