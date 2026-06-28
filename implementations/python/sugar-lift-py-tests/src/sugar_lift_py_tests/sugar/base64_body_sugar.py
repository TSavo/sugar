from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.floor import StringValue, TermValue
from sugar_lift_py_tests.ir import Formula, atomic, eq, make_var, num, str_const
from sugar_lift_py_tests.outcome import complete_value

from .alphabet_literal_sugar import AlphabetLiteralSugar
from .bitwise_base64_sugar import BitwiseBase64Sugar
from .ord_sugar import OrdSugar


@dataclass(frozen=True)
class Base64BodySugar:
    parameter: str
    alphabet: AlphabetLiteralSugar
    ords: tuple[OrdSugar, OrdSugar, OrdSugar]
    return_sugar: BitwiseBase64Sugar

    def __post_init__(self) -> None:
        if not isinstance(self.alphabet, AlphabetLiteralSugar):
            raise TypeError("Base64BodySugar alphabet must be factory-built")
        if len(self.ords) != 3 or not all(isinstance(ord_, OrdSugar) for ord_ in self.ords):
            raise TypeError("Base64BodySugar ords must be factory-built")
        if not isinstance(self.return_sugar, BitwiseBase64Sugar):
            raise TypeError("Base64BodySugar return sugar must be factory-built")

    @classmethod
    def from_site(
        cls,
        site,
        *,
        alphabet: AlphabetLiteralSugar,
        ords: tuple[OrdSugar, OrdSugar, OrdSugar],
        return_sugar: BitwiseBase64Sugar,
    ) -> "Base64BodySugar | None":
        function = site.node
        if not isinstance(function, ast.FunctionDef):
            return None
        if len(function.args.args) != 1 or len(function.body) != 5:
            return None
        parameter = function.args.args[0].arg
        return cls(
            parameter=parameter,
            alphabet=alphabet,
            ords=ords,
            return_sugar=return_sugar,
        )

    def apply(self, argument: StringValue):
        del argument
        raise TypeError(
            "Base64BodySugar lowers to ProofIR; call constraint_formulas instead of "
            "computing base64 in Python"
        )

    def factory_steps(self, function: ast.FunctionDef) -> list[tuple[str, str, ast.stmt, str]]:
        return [
            ("AlphabetLiteralSugar", "Assign", function.body[0], "StringValue"),
            *[
                ("OrdSugar", "Assign", stmt, "TermValue")
                for stmt in function.body[1:4]
            ],
            ("BitwiseBase64Sugar", "Return", function.body[4], "StringValue"),
        ]

    def constraint_formulas(self, argument: StringValue) -> list[Formula]:
        alphabet = complete_value(self.alphabet.desugar(), owner="Base64BodySugar alphabet")
        payload = self.return_sugar.payload_json(
            input_value=argument.value,
            alphabet=alphabet.value,
            alphabet_name=self.alphabet.name,
            byte_names=[ord_sugar.target for ord_sugar in self.ords],
        )
        return [
            eq(make_var(self.alphabet.name), str_const(alphabet.value)),
            *[
                eq(make_var(ord_sugar.target), num(ord(argument.value[ord_sugar.index])))
                for ord_sugar in self.ords
            ],
            atomic("str.eq-bv-blocks", [make_var("out"), str_const(payload)]),
        ]
