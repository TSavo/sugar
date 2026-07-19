from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment


def test_authenticated_bare_type_call_selects_registered_recognizer() -> None:
    site = SourceFragment.from_node(
        ast.parse("type(1)", mode="eval").body, "type.py"
    )
    context = FactoryBuildContext(filename="type.py", catalog=default_catalog())
    built = build_node(
        site, filename="type.py", role=SugarRole.TERM, ctx=context
    )
    assert built.audit_row.selected == "BuiltinTypeCallSugar"


def test_receiver_qualified_type_call_stays_outside_partition() -> None:
    site = SourceFragment.from_node(
        ast.parse("obj.type(1)", mode="eval").body, "type.py"
    )
    context = FactoryBuildContext(filename="type.py", catalog=default_catalog())
    built = build_node(
        site, filename="type.py", role=SugarRole.TERM, ctx=context
    )
    assert built.audit_row.selected != "BuiltinTypeCallSugar"


def test_shadowed_type_parameter_stays_outside_partition() -> None:
    source = "def test_type(type, value):\n    assert type(value) == int\n"
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "type"
    )
    site = SourceFragment.from_node(call, "type_shadow.py", source=source)
    context = FactoryBuildContext(filename="type_shadow.py", catalog=default_catalog())
    built = build_node(
        site, filename="type_shadow.py", role=SugarRole.TERM, ctx=context
    )
    assert built.audit_row.selected != "BuiltinTypeCallSugar"


def test_class_body_type_member_does_not_revoke_later_bare_type() -> None:
    """Nested class stores named ``type`` must not shadow module bare builtin.

    Corpus (numpy scalarmath/multiarray): a ClassDef earlier in the module
    with a method or attribute ``type`` was wrongly revoking ``type(res)``
    universe ownership after logo-table drains. Python keeps the builtin
    visible outside that class namespace.
    """

    source = (
        "class Holder:\n"
        "    def type(self, value):\n"
        "        return value\n"
        "\n"
        "def test_a(value):\n"
        "    assert type(value) is int\n"
    )
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "type"
        and node.lineno > 3
    )
    site = SourceFragment.from_node(call, "type_class_member.py", source=source)
    context = FactoryBuildContext(
        filename="type_class_member.py", catalog=default_catalog()
    )
    built = build_node(
        site, filename="type_class_member.py", role=SugarRole.TERM, ctx=context
    )
    assert built.audit_row.selected == "BuiltinTypeCallSugar"


def test_module_level_type_assignment_still_revokes() -> None:
    source = (
        "type = lambda value: value\n"
        "\n"
        "def test_a(value):\n"
        "    assert type(value) is int\n"
    )
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "type"
    )
    site = SourceFragment.from_node(call, "type_assign.py", source=source)
    context = FactoryBuildContext(filename="type_assign.py", catalog=default_catalog())
    built = build_node(
        site, filename="type_assign.py", role=SugarRole.TERM, ctx=context
    )
    assert built.audit_row.selected != "BuiltinTypeCallSugar"


def test_def_type_function_still_revokes() -> None:
    source = (
        "def type(value):\n"
        "    return value\n"
        "\n"
        "def test_a(value):\n"
        "    assert type(value) is int\n"
    )
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "type"
        and node.lineno > 3
    )
    site = SourceFragment.from_node(call, "type_def.py", source=source)
    context = FactoryBuildContext(filename="type_def.py", catalog=default_catalog())
    built = build_node(
        site, filename="type_def.py", role=SugarRole.TERM, ctx=context
    )
    assert built.audit_row.selected != "BuiltinTypeCallSugar"


def test_dtype_attribute_type_call_stays_loud() -> None:
    """Attribute ``dt.type(...)`` is not bare builtin type — stays unowned."""

    source = (
        "def test_a(dt):\n"
        "    assert dt.type(0) is not None\n"
    )
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "type"
    )
    site = SourceFragment.from_node(call, "dtype_type.py", source=source)
    context = FactoryBuildContext(filename="dtype_type.py", catalog=default_catalog())
    built = build_node(
        site, filename="dtype_type.py", role=SugarRole.TERM, ctx=context
    )
    assert built.audit_row.selected != "BuiltinTypeCallSugar"
