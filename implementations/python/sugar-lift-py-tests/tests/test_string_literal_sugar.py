"""A string literal (`"abc"`) is a PrimitiveLiteral. Int/float own numbers; this
sugar owns `type(...) is str` and reduces to StringValue -- the string as a term."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import Complete


def _build_term(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source, mode="eval").body
    return build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar, ctx


def test_string_literal_builds_and_desugars_to_string_value() -> None:
    sugar, ctx = _build_term('"abc"')
    from sugar_lift_py_tests.sugar.string_literal_sugar import StringLiteralSugar

    assert isinstance(sugar, StringLiteralSugar)
    assert sugar.desugar(ctx) == Complete(StringValue("abc"))
