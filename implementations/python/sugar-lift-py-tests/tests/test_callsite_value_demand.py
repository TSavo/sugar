from __future__ import annotations

import ast

from factory_reduce import fol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import SourceFragment
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    CallSiteValue,
    ObjectValue,
    ReturnValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, num, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar.object_equality_term_sugar import ObjectEqualityTermSugar


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
        owner="callsite value demand",
    )


def _reduce_function_return(source: str, name: str):
    module = ast.parse(source)
    ctx = _ctx_for_module(source)
    function = next(
        stmt
        for stmt in module.body
        if isinstance(stmt, ast.FunctionDef) and stmt.name == name
    )
    block = ctx.build_body(Block.of(function.body), SugarRole.STATEMENT)
    value = complete_value(block.reduce(ctx), owner="function return demand")
    assert len(value.statements) == 1
    returned = value.statements[0]
    assert isinstance(returned, ReturnValue)
    return returned.value


def test_callsite_projects_to_bridge_but_floors_only_when_value_is_demanded() -> None:
    source = """\
def h():
    return 1

def g():
    return h()

def f():
    return g()
"""

    call_value = _reduce_expr(source, "f()")
    assert fol(floor_to_term(call_value, owner="callsite projection")) == fol(
        ctor("call:f", [])
    )

    indexed = _reduce_expr(source, "[10, 20, 30][f()]")
    assert indexed == TermValue(20)


def test_object_constructor_can_stand_inside_array_literal_as_identity_floor() -> None:
    source = """\
class Mult:
    pass
"""

    value = _reduce_expr(source, "[Mult()]")

    assert isinstance(value, ArrayLiteral)
    assert isinstance(value.items[0], ObjectValue)
    assert fol(floor_to_term(value, owner="object array")) == fol(
        ctor(
            "array",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Mult"), str_const("t.py:1:1")],
                )
            ],
        )
    )


def test_constructor_bound_field_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

def t():
    x = X(1)
    return [10, 20, 30][x.x]
"""

    assert _reduce_function_return(source, "t") == TermValue(20)


def test_constructor_method_return_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

    def getX(self):
        return self.x

def t():
    x = X(1)
    return [10, 20, 30][x.getX()]
"""

    assert _reduce_function_return(source, "t") == TermValue(20)


def test_object_multiply_projects_to_dunder_method_bridge() -> None:
    source = """\
class Mult:
    def __mul__(self, other):
        return 1
"""

    value = _reduce_expr(source, "Mult() * Mult()")

    assert isinstance(value, CallSiteValue)
    assert fol(floor_to_term(value, owner="object multiply")) == fol(
        ctor(
            "call:Mult.__mul__",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Mult"), str_const("t.py:1:0")],
                ),
                ctor(
                    "py.object.identity",
                    [str_const("Mult"), str_const("t.py:1:9")],
                ),
            ],
        )
    )


def test_object_multiply_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

    def __mul__(self, other):
        return other.x
"""

    value = _reduce_expr(source, "[10, 20, 30][X(0) * X(1)]")

    assert value == TermValue(20)


def test_object_equality_projects_to_dunder_method_bridge() -> None:
    source = """\
class Eq:
    def __eq__(self, other):
        return 1
"""

    fragment = SourceFragment.from_node(ast.parse("Eq() == Eq()", mode="eval").body, "t.py")
    assert ObjectEqualityTermSugar.owns(fragment)

    value = _reduce_expr(source, "Eq() == Eq()")

    assert isinstance(value, CallSiteValue)
    assert fol(floor_to_term(value, owner="object equality")) == fol(
        ctor(
            "call:Eq.__eq__",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Eq"), str_const("t.py:1:0")],
                ),
                ctor(
                    "py.object.identity",
                    [str_const("Eq"), str_const("t.py:1:8")],
                ),
            ],
        )
    )


def test_reflected_object_multiply_projects_to_dunder_method_bridge() -> None:
    source = """\
class Mult:
    def __rmul__(self, other):
        return 1
"""

    value = _reduce_expr(source, "2 * Mult()")

    assert isinstance(value, CallSiteValue)
    assert fol(floor_to_term(value, owner="reflected object multiply")) == fol(
        ctor(
            "call:Mult.__rmul__",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Mult"), str_const("t.py:1:4")],
                ),
                num(2),
            ],
        )
    )


def test_reflected_object_multiply_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

    def __rmul__(self, other):
        return self.x
"""

    value = _reduce_expr(source, "[10, 20, 30][2 * X(1)]")

    assert value == TermValue(20)


def test_object_add_projects_to_dunder_method_bridge() -> None:
    source = """\
class Add:
    def __add__(self, other):
        return 1
"""

    value = _reduce_expr(source, "Add() + Add()")

    assert isinstance(value, CallSiteValue)
    assert fol(floor_to_term(value, owner="object add")) == fol(
        ctor(
            "call:Add.__add__",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Add"), str_const("t.py:1:0")],
                ),
                ctor(
                    "py.object.identity",
                    [str_const("Add"), str_const("t.py:1:8")],
                ),
            ],
        )
    )


def test_reflected_object_add_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

    def __radd__(self, other):
        return self.x
"""

    value = _reduce_expr(source, "[10, 20, 30][2 + X(1)]")

    assert value == TermValue(20)


def test_object_subtract_projects_to_dunder_method_bridge() -> None:
    source = """\
class Sub:
    def __sub__(self, other):
        return 1
"""

    value = _reduce_expr(source, "Sub() - Sub()")

    assert isinstance(value, CallSiteValue)
    assert fol(floor_to_term(value, owner="object subtract")) == fol(
        ctor(
            "call:Sub.__sub__",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Sub"), str_const("t.py:1:0")],
                ),
                ctor(
                    "py.object.identity",
                    [str_const("Sub"), str_const("t.py:1:8")],
                ),
            ],
        )
    )


def test_reflected_object_subtract_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

    def __rsub__(self, other):
        return self.x
"""

    value = _reduce_expr(source, "[10, 20, 30][2 - X(1)]")

    assert value == TermValue(20)
