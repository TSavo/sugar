from __future__ import annotations

import pytest

from sugar_lift_python_source import ast_template, bind_lifter, value_pins
from sugar_lift_python_source import typed_node_api as typed


class RenamedFutureStatement(typed.stmt):
    _child_fields: tuple[str, ...] = ()


def test_every_statement_consumer_is_total_and_future_variants_are_loud() -> None:
    node = object.__new__(RenamedFutureStatement)

    with pytest.raises(ast_template.UnsupportedStatementVariant):
        ast_template.stmt_to_template(node, [])
    with pytest.raises(bind_lifter.UnsupportedStatementVariant):
        bind_lifter._shape_stmt_with_bindings(node, top_level=False)
    with pytest.raises(value_pins.UnsupportedStatementVariant):
        list(value_pins._statement_binding_events(node))


def test_current_statement_grammar_is_the_explicit_partition() -> None:
    running = ast_template.AST_STATEMENT_TYPES
    assert ast_template.AST_STATEMENT_TYPE_NAMES == {item.__name__ for item in running}
    assert bind_lifter.AST_STATEMENT_TYPES == running
    assert bind_lifter.AST_STATEMENT_TYPE_NAMES == {item.__name__ for item in running}
    assert value_pins.AST_STATEMENT_TYPES == running
    assert value_pins.AST_STATEMENT_TYPE_NAMES == {item.__name__ for item in running}
    assert issubclass(ast_template.UnsupportedStatementGrammar, RuntimeError)
    assert issubclass(bind_lifter.UnsupportedStatementGrammar, RuntimeError)
    assert issubclass(value_pins.UnsupportedStatementGrammar, RuntimeError)


def test_bind_lifter_reads_through_the_typed_source_door(monkeypatch) -> None:
    seen: list[typed.Module] = []
    parse = typed.parse

    def recording_parse(source: str, *, filename: str) -> typed.Module:
        module = parse(source, filename=filename)
        assert isinstance(module, typed.Module)
        assert all(isinstance(node, typed.AST) for node in module.walk())
        seen.append(module)
        return module

    monkeypatch.setattr(typed, "parse", recording_parse)
    source = "def renamed_nonvendor(operand):\n    return operand\n"

    binding = bind_lifter.lift_source(source, "renamed_nonvendor.py")

    assert binding.ir
    assert len(seen) == 1
