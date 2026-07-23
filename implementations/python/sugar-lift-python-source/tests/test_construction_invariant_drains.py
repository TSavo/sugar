from __future__ import annotations

import ast

import pytest

from sugar_lift_python_source import ast_template, bind_lifter, lifter, value_pins


class RenamedFutureStatement(ast.stmt):
    _fields: tuple[str, ...] = ()


def test_every_statement_consumer_is_total_and_future_variants_are_loud() -> None:
    node = RenamedFutureStatement()

    with pytest.raises(ast_template.UnsupportedStatementVariant):
        ast_template.stmt_to_template(node, [])
    with pytest.raises(bind_lifter.UnsupportedStatementVariant):
        bind_lifter._shape_stmt_with_bindings(node, top_level=False)
    with pytest.raises(lifter._UnsupportedSyntax):
        lifter._Emitter.statement(object.__new__(lifter._Emitter), node)
    with pytest.raises(lifter._UnsupportedSyntax):
        lifter._slot_entries(node)
    with pytest.raises(lifter._UnsupportedSyntax):
        lifter._class_body_attribute_sources(node)
    with pytest.raises(lifter._UnsupportedSyntax):
        lifter._module_statement_bound_names(node)
    with pytest.raises(value_pins.UnsupportedStatementVariant):
        list(value_pins._statement_binding_events(node))


def test_current_statement_grammar_is_the_explicit_partition() -> None:
    running = frozenset(
        statement for statement in ast.stmt.__subclasses__() if statement.__module__ == "ast"
    )
    assert ast_template.AST_STATEMENT_TYPES == running
    assert ast_template.AST_STATEMENT_TYPE_NAMES == {item.__name__ for item in running}
    assert bind_lifter.AST_STATEMENT_TYPES == running
    assert bind_lifter.AST_STATEMENT_TYPE_NAMES == {item.__name__ for item in running}
    assert lifter.AST_STATEMENT_TYPES == running
    assert lifter.AST_STATEMENT_TYPE_NAMES == {item.__name__ for item in running}
    assert value_pins.AST_STATEMENT_TYPES == running
    assert value_pins.AST_STATEMENT_TYPE_NAMES == {item.__name__ for item in running}
    assert issubclass(ast_template.UnsupportedStatementGrammar, RuntimeError)
    assert issubclass(bind_lifter.UnsupportedStatementGrammar, RuntimeError)
    assert issubclass(lifter.UnsupportedStatementGrammar, RuntimeError)
    assert issubclass(value_pins.UnsupportedStatementGrammar, RuntimeError)


def test_renamed_external_values_and_decorators_receive_no_spelling_authority() -> None:
    source = (
        "import arbitrary_provider as provider\n"
        "\n"
        "@provider.transparent_looking\n"
        "def f(value=provider.magic_constant):\n"
        "    return value\n"
    )

    result = lifter.lift_source(source, "renamed_provider.py")

    assert result.refusals
    assert any(row["kind"] == "decorator-refused" for row in result.refusals)
    assert not any(str(row.get("fnName", "")).endswith(".f") for row in result.ir)


def test_decorator_spelling_never_confers_transparency_or_stub_authority() -> None:
    source = (
        "def overload(fn):\n"
        "    return fn\n"
        "\n"
        "@overload\n"
        "def f():\n"
        "    ...\n"
        "\n"
        "def set_module(value):\n"
        "    return lambda fn: fn\n"
        "\n"
        "@set_module('renamed-vendor')\n"
        "def g():\n"
        "    return 1\n"
    )

    result = lifter.lift_source(source, "spelling_is_not_authority.py")

    refused = {row["function"] for row in result.refusals if row["kind"] == "decorator-refused"}
    assert any(name and name.endswith(".f") for name in refused)
    assert any(name and name.endswith(".g") for name in refused)
    assert not any(
        str(row.get("fnName", "")).endswith((".f", ".g")) for row in result.ir
    )


def test_import_alias_does_not_turn_external_default_into_a_literal() -> None:
    source = "from numpy import nan as renamed\ndef f(value=renamed):\n    return value\n"

    result = lifter.lift_source(source, "aliased_external_default.py")

    assert any(row["kind"] == "non-literal-default" for row in result.refusals)
