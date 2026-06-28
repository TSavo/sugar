from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryBuildContext, SourceSite, default_catalog
from sugar_lift_py_tests.factory.sugar_constructors import (
    build_base64_body_sugar,
    build_function_call_sugar,
)
from sugar_lift_py_tests.floor import StringValue, TermValue
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
    assert complete_value(sugar.apply(StringValue("abc")), owner="body") == StringValue(
        "YWJj"
    )


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
    assert complete_value(
        sugar.apply(
            {
                "alphabet": BASE64_ALPHABET,
                "b0": 97,
                "b1": 98,
                "b2": 99,
            }
        ),
        owner="bitwise base64",
    ) == StringValue("YWJj")
