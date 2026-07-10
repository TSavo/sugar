from __future__ import annotations

import ast

import pytest
from factory_reduce import fol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import factory_panic
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import BlockValue, CallSiteValue, TermValue
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
    return complete_value(
        ctx.build_body(node, SugarRole.TERM).reduce(ctx),
        owner="attribute descriptor",
    )


def _reduce_block(source: str, statements: str) -> BlockValue:
    full_source = f"{source.rstrip()}\n\ndef _probe():\n{statements}\n"
    module = ast.parse(full_source)
    ctx = _ctx_for_module(full_source)
    function = next(
        stmt
        for stmt in module.body
        if isinstance(stmt, ast.FunctionDef) and stmt.name == "_probe"
    )
    outcome = ctx.build_body(Block.of(function.body), SugarRole.STATEMENT).reduce(ctx)
    return complete_value(outcome, owner="attribute descriptor block")


def _object_identity(class_name: str, blame: str):
    return ctor("py.object.identity", [str_const(class_name), str_const(blame)])


def test_getattribute_dunder_wins_before_constructor_field() -> None:
    source = """\
class Box:
    def __init__(self):
        self.value = 0

    def __getattribute__(self, name):
        return 1
"""

    value = _reduce_expr(source, "Box().value")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__getattribute__"
    assert fol(floor_to_term(value, owner="getattribute dunder")) == fol(
        ctor(
            "call:Box.__getattribute__",
            [
                _object_identity("Box", "t.py:1:0"),
                str_const("value"),
            ],
        )
    )


def test_getattribute_dunder_can_drive_array_index_value_demand() -> None:
    source = """\
class Box:
    def __getattribute__(self, name):
        return 1
"""

    value = _reduce_expr(source, "[10, 20, 30][Box().value]")

    assert value == TermValue(20)


def test_descriptor_get_dunder_projects_class_field_descriptor() -> None:
    source = """\
class Descriptor:
    def __get__(self, obj, owner):
        return 1

class Box:
    value = Descriptor()
"""

    value = _reduce_expr(source, "Box().value")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Descriptor.__get__"
    assert fol(floor_to_term(value, owner="descriptor get dunder")) == fol(
        ctor(
            "call:Descriptor.__get__",
            [
                _object_identity("Descriptor", "t.py:6:12"),
                _object_identity("Box", "t.py:1:0"),
                str_const("Box"),
            ],
        )
    )


def test_descriptor_get_dunder_can_drive_array_index_value_demand() -> None:
    source = """\
class Descriptor:
    def __get__(self, obj, owner):
        return 1

class Box:
    value = Descriptor()
"""

    value = _reduce_expr(source, "[10, 20, 30][Box().value]")

    assert value == TermValue(20)


def test_dir_builtin_projects_to_dir_dunder_method() -> None:
    source = """\
class Box:
    def __dir__(self):
        return 1
"""

    value = _reduce_expr(source, "dir(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__dir__"


def test_attribute_assign_projects_to_setattr_dunder_floor() -> None:
    # AttributeAssignSugar owns `obj.value = ...` and dispatches to __setattr__.
    source = """\
class Box:
    def __setattr__(self, name, value):
        return 1
"""

    block = _reduce_block(
        source,
        "    obj = Box()\n" "    obj.value = 2",
    )

    assert len(block.statements) == 1
    value = block.statements[0]
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__setattr__"


def test_attribute_delete_projects_to_delattr_dunder_floor() -> None:
    # AttributeDeleteSugar owns `del obj.value` and dispatches to __delattr__.
    source = """\
class Box:
    def __delattr__(self, name):
        return 1
"""

    block = _reduce_block(
        source,
        "    obj = Box()\n" "    del obj.value",
    )

    assert len(block.statements) == 1
    value = block.statements[0]
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__delattr__"


def test_descriptor_set_dunder_wins_for_attribute_assignment() -> None:
    source = """\
class Descriptor:
    def __set__(self, obj, value):
        return 1

class Box:
    value = Descriptor()
"""

    block = _reduce_block(
        source,
        "    obj = Box()\n" "    obj.value = 2",
    )

    assert len(block.statements) == 1
    value = block.statements[0]
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Descriptor.__set__"


def test_descriptor_delete_dunder_wins_for_attribute_delete() -> None:
    source = """\
class Descriptor:
    def __delete__(self, obj):
        return 1

class Box:
    value = Descriptor()
"""

    block = _reduce_block(
        source,
        "    obj = Box()\n" "    del obj.value",
    )

    assert len(block.statements) == 1
    value = block.statements[0]
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Descriptor.__delete__"


def test_set_name_descriptor_protocol_is_loud_class_construction_gap() -> None:
    source = """\
class Descriptor:
    def __set_name__(self, owner, name):
        return 1

class Box:
    value = Descriptor()
"""

    with pytest.raises(FactoryGap) as raised:
        _reduce_expr(source, "Box().value")

    assert (
        raised.value.info.to_json()["requested"]
        == "class descriptor __set_name__ effect"
    )
    assert raised.value.info.to_json()["observed"] == "Box.value"
