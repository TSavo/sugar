from __future__ import annotations

import ast

from factory_reduce import fol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import CallSiteValue, StringValue, SymbolicValue
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term


def _ctx_for_module(source: str) -> FactoryBuildContext:
    module = ast.parse(source)
    resolver = {
        stmt.name: stmt
        for stmt in module.body
        if isinstance(stmt, (ast.FunctionDef, ast.ClassDef))
    }
    return FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        name_resolver=resolver,
    )


def _reduce_expr(source: str, expr: str):
    ctx = _ctx_for_module(source)
    node = ast.parse(expr, mode="eval").body
    value = complete_value(
        ctx.build_body(node, SugarRole.TERM).reduce(ctx),
        owner="display conversion dunder bridge",
    )
    return value, ctx


def _object_identity(class_name: str, blame: str):
    return ctor("py.object.identity", [str_const(class_name), str_const(blame)])


def test_str_builtin_projects_object_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __str__(self):
        return "display"
"""

    value, ctx = _reduce_expr(source, "str(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__str__"
    assert fol(floor_to_term(value, owner="str dunder bridge")) == fol(
        ctor("call:Box.__str__", [_object_identity("Box", "t.py:1:4")])
    )
    assert force_floor(value, ctx, owner="str dunder bridge") == StringValue("display")


def test_bytes_builtin_projects_object_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __bytes__(self):
        return b"OK"
"""

    value, ctx = _reduce_expr(source, "bytes(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__bytes__"
    assert fol(floor_to_term(value, owner="bytes dunder bridge")) == fol(
        ctor("call:Box.__bytes__", [_object_identity("Box", "t.py:1:6")])
    )
    assert force_floor(value, ctx, owner="bytes dunder bridge") == SymbolicValue(
        ctor("python:bytes", [str_const("4f4b")])
    )


def test_format_builtin_projects_object_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __format__(self, spec):
        return spec
"""

    value, ctx = _reduce_expr(source, 'format(Box(), "brief")')

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__format__"
    assert fol(floor_to_term(value, owner="format dunder bridge")) == fol(
        ctor(
            "call:Box.__format__",
            [_object_identity("Box", "t.py:1:7"), str_const("brief")],
        )
    )
    assert force_floor(value, ctx, owner="format dunder bridge") == StringValue("brief")


def test_format_builtin_without_spec_passes_empty_format_spec() -> None:
    source = """\
class Box:
    def __format__(self, spec):
        return spec
"""

    value, ctx = _reduce_expr(source, "format(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__format__"
    assert fol(floor_to_term(value, owner="format dunder bridge")) == fol(
        ctor(
            "call:Box.__format__",
            [_object_identity("Box", "t.py:1:7"), str_const("")],
        )
    )
    assert force_floor(value, ctx, owner="format dunder bridge") == StringValue("")
