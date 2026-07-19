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
