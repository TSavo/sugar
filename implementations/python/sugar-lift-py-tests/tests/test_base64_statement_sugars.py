from __future__ import annotations

import ast
import json

import pytest

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryBuildContext, SourceSite, default_catalog
from sugar_lift_py_tests.factory.sugar_constructors import (
    build_base64_body_sugar,
    build_function_call_sugar,
)
from sugar_lift_py_tests.floor import StringValue, TermValue
from sugar_lift_py_tests.ir import formula_to_value
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.alphabet_literal_sugar import (
    BASE64_ALPHABET,
    AlphabetLiteralSugar,
)
from sugar_lift_py_tests.sugar.base64_body_sugar import Base64BodySugar
from sugar_lift_py_tests.sugar.bitwise_base64_sugar import BitwiseBase64Sugar
from sugar_lift_py_tests.sugar.function_call_sugar import FunctionCallSugar
from sugar_lift_py_tests.sugar.ord_sugar import OrdSugar
from sugar_lift_py_tests.sugar_body import SugarBody


ENCODE_BASE64 = f'''
def encodeBase64(value):
    alphabet = "{BASE64_ALPHABET}"
    b0 = ord(value[0])
    b1 = ord(value[1])
    b2 = ord(value[2])
    return (
        alphabet[b0 >> 2]
        + alphabet[((b0 & 3) << 4) | (b1 >> 4)]
        + alphabet[((b1 & 15) << 2) | (b2 >> 6)]
        + alphabet[b2 & 63]
    )
'''


def test_alphabet_literal_sugar_is_site_born_without_raw_ast_storage() -> None:
    stmt = ast.parse(f'alphabet = "{BASE64_ALPHABET}"').body[0]

    sugar = AlphabetLiteralSugar.from_site(SourceSite.from_node(stmt, "base64.py"))

    assert sugar is not None
    assert sugar.name == "alphabet"
    assert not hasattr(sugar, "stmt")
    assert complete_value(sugar.desugar(), owner="alphabet") == StringValue(
        BASE64_ALPHABET
    )


def test_ord_sugar_is_site_born_without_raw_ast_storage() -> None:
    stmt = ast.parse("b0 = ord(value[0])").body[0]

    sugar = OrdSugar.from_site(
        SourceSite.from_node(stmt, "base64.py"),
        source_name="value",
    )

    assert sugar is not None
    assert sugar.target == "b0"
    assert sugar.source_name == "value"
    assert sugar.index == 0
    assert not hasattr(sugar, "stmt")
    assert complete_value(sugar.apply(StringValue("abc")), owner="ord") == TermValue(97)


def test_function_call_sugar_is_site_born_without_raw_ast_storage() -> None:
    module = ast.parse(
        '''
def encodeBase64(value):
    return "YWJj"

encodeBase64("abc")
'''
    )
    fn = module.body[0]
    expr = module.body[1]
    assert isinstance(fn, ast.FunctionDef)
    assert isinstance(expr, ast.Expr)

    ctx = FactoryBuildContext(
        filename="base64.py",
        catalog=default_catalog(),
        name_resolver={"encodeBase64": fn},
    )
    sugar = build_function_call_sugar(
        SourceSite.from_node(expr.value, "base64.py"),
        ctx,
    )

    assert sugar is not None
    assert sugar.target_name == "encodeBase64"
    assert not hasattr(sugar, "call")
    assert not hasattr(sugar, "function")
    assert complete_value(sugar.desugar(), owner="call") == StringValue("YWJj")


def test_function_call_sugar_requires_factory_built_argument() -> None:
    body = SugarBody(sugar=object(), role=SugarRole.TERM)

    with pytest.raises(TypeError, match="FunctionCallSugar argument must be factory-built"):
        FunctionCallSugar(
            target_name="encodeBase64",
            argument=object(),  # type: ignore[arg-type]
            body=body,
        )


def test_base64_body_sugar_is_site_born_without_raw_function_storage() -> None:
    fn = ast.parse(ENCODE_BASE64).body[0]
    assert isinstance(fn, ast.FunctionDef)

    ctx = FactoryBuildContext(filename="base64.py", catalog=default_catalog())
    sugar = build_base64_body_sugar(SourceSite.from_node(fn, "base64.py"), ctx)

    assert sugar is not None
    assert sugar.parameter == "value"
    assert not hasattr(sugar, "function")
    with pytest.raises(TypeError, match="lowers to ProofIR"):
        sugar.apply(StringValue("abc"))
    formulas = [
        json.loads(encode_jcs(formula_to_value(formula)))
        for formula in sugar.constraint_formulas(StringValue("abc"))
    ]
    assert formulas[:4] == [
        {
            "args": [
                {"kind": "var", "name": "alphabet"},
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "String"},
                    "value": BASE64_ALPHABET,
                },
            ],
            "kind": "atomic",
            "name": "=",
        },
        {
            "args": [
                {"kind": "var", "name": "b0"},
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "Int"},
                    "value": 97,
                },
            ],
            "kind": "atomic",
            "name": "=",
        },
        {
            "args": [
                {"kind": "var", "name": "b1"},
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "Int"},
                    "value": 98,
                },
            ],
            "kind": "atomic",
            "name": "=",
        },
        {
            "args": [
                {"kind": "var", "name": "b2"},
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "Int"},
                    "value": 99,
                },
            ],
            "kind": "atomic",
            "name": "=",
        },
    ]
    atom = formulas[4]
    assert atom["name"] == "str.eq-bv-blocks"
    payload = json.loads(atom["args"][1]["value"])
    assert payload["input_bytes"] == [97, 98, 99]
    assert payload["vars"] == ["b0", "b1", "b2"]
    assert len(payload["per_char"]) == 4
    assert payload["table"] == [ord(ch) for ch in BASE64_ALPHABET]


def test_base64_body_sugar_requires_factory_built_children() -> None:
    with pytest.raises(TypeError, match="Base64BodySugar alphabet must be factory-built"):
        Base64BodySugar(
            parameter="value",
            alphabet=object(),  # type: ignore[arg-type]
            ords=(),  # type: ignore[arg-type]
            return_sugar=object(),  # type: ignore[arg-type]
        )


def test_bitwise_base64_sugar_is_site_born_without_raw_return_storage() -> None:
    fn = ast.parse(ENCODE_BASE64).body[0]
    assert isinstance(fn, ast.FunctionDef)
    stmt = fn.body[4]

    sugar = BitwiseBase64Sugar.from_site(SourceSite.from_node(stmt, "base64.py"))

    assert sugar is not None
    assert not hasattr(sugar, "stmt")
    payload = json.loads(
        sugar.payload_json(
            input_value="abc",
            alphabet=BASE64_ALPHABET,
            alphabet_name="alphabet",
            byte_names=["b0", "b1", "b2"],
        )
    )
    assert payload["input_bytes"] == [97, 98, 99]
    assert payload["vars"] == ["b0", "b1", "b2"]
    assert payload["table"] == [ord(ch) for ch in BASE64_ALPHABET]
    assert payload["per_char"][0] == {
        "args": [
            {"kind": "var", "name": "b0"},
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": 2,
            },
        ],
        "kind": "ctor",
        "name": "bv32.lshr",
    }
