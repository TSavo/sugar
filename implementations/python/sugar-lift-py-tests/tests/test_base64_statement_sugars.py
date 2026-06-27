from __future__ import annotations

import ast

from sugar_lift_py_tests.factory import SourceSite
from sugar_lift_py_tests.floor import StringValue, TermValue
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.alphabet_literal_sugar import (
    BASE64_ALPHABET,
    AlphabetLiteralSugar,
)
from sugar_lift_py_tests.sugar.function_call_sugar import FunctionCallSugar
from sugar_lift_py_tests.sugar.ord_sugar import OrdSugar


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

    sugar = FunctionCallSugar.from_site(
        SourceSite.from_node(expr.value, "base64.py"),
        functions_by_name={"encodeBase64": fn},
    )

    assert sugar is not None
    assert sugar.target_name == "encodeBase64"
    assert not hasattr(sugar, "call")
    assert not hasattr(sugar, "function")
    assert complete_value(sugar.desugar(), owner="call") == StringValue("YWJj")
