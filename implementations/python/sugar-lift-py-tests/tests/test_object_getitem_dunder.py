from __future__ import annotations

import ast

from factory_reduce import fol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.ir import ctor, num, str_const
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
    return complete_value(
        ctx.build_body(node, SugarRole.TERM).reduce(ctx),
        owner="object getitem",
    )


def test_object_getitem_projects_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __getitem__(self, key):
        return 1
"""

    value = _reduce_expr(source, "Box()[0]")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__getitem__"
    assert fol(floor_to_term(value, owner="object getitem bridge")) == fol(
        ctor(
            "call:Box.__getitem__",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Box"), str_const("t.py:1:0")],
                ),
                num(0),
            ],
        )
    )


def test_object_getitem_can_drive_array_index_value_demand() -> None:
    source = """\
class Box:
    def __init__(self, x):
        self.x = x

    def __getitem__(self, key):
        return self.x
"""

    value = _reduce_expr(source, "[10, 20, 30][Box(1)[0]]")

    assert value == TermValue(20)
