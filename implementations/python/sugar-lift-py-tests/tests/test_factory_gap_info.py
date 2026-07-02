from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap_info import FactoryGapInfo
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.outcome import complete_value


def _ctx_for_module(source: str) -> FactoryBuildContext:
    module = ast.parse(source)
    resolver = {
        stmt.name: stmt
        for stmt in module.body
        if isinstance(stmt, (ast.ClassDef, ast.FunctionDef))
    }
    return FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        name_resolver=resolver,
    )


def _reduce_expr(source: str, expr: str):
    ctx = _ctx_for_module(source)
    node = ast.parse(expr, mode="eval").body
    return complete_value(
        ctx.build_body(node, SugarRole.TERM).reduce(ctx),
        owner="factory gap info",
    )


def _build_expr(source: str, expr: str):
    ctx = _ctx_for_module(source)
    node = ast.parse(expr, mode="eval").body
    return ctx.build_body(SourceFragment.from_node(node, "t.py"), SugarRole.TERM), ctx


def test_to_json_carries_gap_kind_and_locus() -> None:
    info = FactoryGapInfo(
        owner="o",
        blame="b",
        observed="x",
        requested="r",
        fix="f",
        gap_kind="Floor",
        gap_locus="Reduce",
    )

    data = info.to_json()

    assert data["gap_kind"] == "Floor"
    assert data["gap_locus"] == "Reduce"


def test_to_json_defaults_present() -> None:
    info = FactoryGapInfo(owner="o", blame="b", observed="x", requested="r", fix="f")

    data = info.to_json()

    assert data["gap_kind"] == "Sugar"
    assert data["gap_locus"] == "AST"


def test_constructor_call_refusal_carries_structured_kind() -> None:
    source = """\
class Box:
    def __init__(self, value):
        self.value = value
"""
    body, ctx = _build_expr(source, "Box()")

    with pytest.raises(FactoryGap) as raised:
        body.reduce(ctx)

    assert raised.value.info["requested"] == "1 constructor arguments"
    assert raised.value.info["gap_kind"] == "Constructor"


def test_set_name_descriptor_gap_carries_structured_kind() -> None:
    source = """\
class Descriptor:
    def __set_name__(self, owner, name):
        return 1

class Box:
    value = Descriptor()
"""

    with pytest.raises(FactoryGap) as raised:
        _reduce_expr(source, "Box().value")

    assert raised.value.info["requested"] == "class descriptor __set_name__ effect"
    assert raised.value.info["gap_kind"] == "Constructor"
