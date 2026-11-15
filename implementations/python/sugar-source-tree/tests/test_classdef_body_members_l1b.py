"""L1b: ClassDef body members — fields, nested ClassDef, a class body's if.

Methods enroll through the FunctionDef door (not reimplemented here).
"""

from __future__ import annotations

import pytest

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.floor import ConstructedClassFieldV1
from sugar_lift_py_tests.sugar.class_definition_sugar import ClassDefinitionSugar
from sugar_lift_py_tests.sugar.if_sugar import IfSugar
from sugar_source_tree.nodes import ClassDef
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _class(src: str, name: str = "C") -> ClassDef:
    seat = f"{name}.py"
    cid = cid_of_json({"source": src, "seat": seat})
    source = SourceFile((src, seat, cid), construction_context=TreeConstructionContextV1.for_test_without_workspace())
    return next(
        node
        for node in source.nodes()
        if isinstance(node, ClassDef) and node.name == name
    )


def test_l1b_simple_fields_construct() -> None:
    sugar = _class("class C:\n" "    a = 1\n" "    b: int = 2\n").sugar()
    assert isinstance(sugar, ClassDefinitionSugar)
    assert sugar.methods == ()
    assert tuple(field.name for field in sugar.fields) == ("a", "b")
    assert all(isinstance(field, ConstructedClassFieldV1) for field in sugar.fields)


def test_l1b_nested_classdef_is_a_field() -> None:
    sugar = _class(
        "class Outer:\n" "    x = 1\n" "    class Inner:\n" "        y = 2\n",
        name="Outer",
    ).sugar()
    assert isinstance(sugar, ClassDefinitionSugar)
    names = tuple(
        (
            field.name
            if isinstance(field, ConstructedClassFieldV1)
            else type(field).__name__
        )
        for field in sugar.fields
    )
    assert names == ("x", "Inner")
    inner = next(
        field for field in sugar.fields if getattr(field, "name", None) == "Inner"
    )
    assert isinstance(inner, ConstructedClassFieldV1)
    assert isinstance(inner.value_sugar, ClassDefinitionSugar)
    assert inner.value_sugar.class_name == "Inner"
    assert tuple(f.name for f in inner.value_sugar.fields) == ("y",)


def test_l1b_a_class_body_if_is_the_one_if_statement() -> None:
    """A class body is a block: its ``if`` is ``IfSugar``, the statement
    every block runs, and each arm's assignment names a row of the
    namespace under its own evaluation key, bound only where its arm ran."""
    sugar = _class(
        "class C:\n" "    if True:\n" "        a = 1\n" "    else:\n" "        a = 2\n"
    ).sugar()
    assert isinstance(sugar.body[0], IfSugar)
    assert tuple(field.name for field in sugar.fields) == ("a", "a")
    assert all(isinstance(field, ConstructedClassFieldV1) for field in sugar.fields)
    assert sugar.branch_fields == frozenset({0, 1})
    keys = {field.evaluation_key for field in sugar.fields}
    assert None not in keys and len(keys) == 2
    value = sugar.desugar().completed_value()
    assert [field.name for field in value.class_fields] == ["a"]
    assert value.class_fields[0].value.value == 1


def test_l1b_elif_chain_is_a_nested_if() -> None:
    sugar = _class(
        "class C:\n"
        "    if False:\n"
        "        a = 1\n"
        "    elif True:\n"
        "        a = 2\n"
        "    else:\n"
        "        a = 3\n"
    ).sugar()
    outer = sugar.body[0]
    assert isinstance(outer, IfSugar)
    # the elif is the else arm's own if
    assert any(isinstance(statement, IfSugar) for statement in outer.else_body)
    assert tuple(field.name for field in sugar.fields) == ("a", "a", "a")
    value = sugar.desugar().completed_value()
    assert [field.name for field in value.class_fields] == ["a"]
    assert value.class_fields[0].value.value == 2


def test_l1b_fields_alongside_sync_method() -> None:
    """Fields construct; method body uses FunctionDef door (not ClassDef)."""
    sugar = _class(
        "class C:\n" "    a = 1\n" "    def m(self):\n" "        return self.a\n"
    ).sugar()
    assert tuple(f.name for f in sugar.fields) == ("a",)
    assert len(sugar.methods) == 1
    assert sugar.methods[0].name == "m"
    assert sugar.methods[0].source_call_frame is not None


def test_l1b_async_method_is_method_member_through_the_function_door() -> None:
    """AsyncFunctionDef is a method member constructed through the FunctionDef
    door -- not "unsupported class member", and (since plan Cut 1) not a
    refusal either: ``contextlib.nullcontext`` carries ``async def __aenter__``
    beside the sync protocol, and refusing the whole class over a member the
    sync protocol never enters kept every enrolled stdlib manager at
    ``force-floor``."""
    from sugar_lift_py_tests.sugar.function_universe_sugar import FunctionUniverseSugar
    from sugar_source_tree.nodes import AsyncFunctionDef

    cls = _class("class C:\n" "    a = 1\n" "    async def m(self):\n" "        return 1\n")
    member = next(m for m in cls.body if isinstance(m, AsyncFunctionDef))
    constructed = cls._construct_class_method_member(member)
    assert constructed.name == "m"
    assert isinstance(constructed.body, FunctionUniverseSugar)
    assert cls.sugar() is not None


