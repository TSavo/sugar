from __future__ import annotations

import pytest

from sugar_lift_python_source import ast_template
from sugar_lift_python_source import typed_node_api as typed


class RenamedFutureStatement(typed.stmt):
    _child_fields: tuple[str, ...] = ()


def test_every_statement_consumer_is_total_and_future_variants_are_loud() -> None:
    node = object.__new__(RenamedFutureStatement)

    with pytest.raises(ast_template.UnsupportedStatementVariant):
        ast_template.stmt_to_template(node, [])


def test_current_statement_grammar_is_the_explicit_partition() -> None:
    running = ast_template.AST_STATEMENT_TYPES
    assert ast_template.AST_STATEMENT_TYPE_NAMES == {item.__name__ for item in running}
    assert issubclass(ast_template.UnsupportedStatementGrammar, RuntimeError)
