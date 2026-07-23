from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests import import_binding


class RenamedFutureStatement(ast.stmt):
    _fields: tuple[str, ...] = ()


def test_import_binding_transfer_rejects_future_statement_variants_loudly() -> None:
    transfer = import_binding._Pass(
        source_cid="blake3-512:" + "0" * 128,
        module_name="fixture",
        module_identities={},
    )
    scope = ast.parse("pass")

    with pytest.raises(import_binding.UnsupportedStatementVariant):
        transfer.statement(RenamedFutureStatement(), {}, scope)


def test_import_binding_statement_partition_matches_running_grammar() -> None:
    running = frozenset(
        statement for statement in ast.stmt.__subclasses__() if statement.__module__ == "ast"
    )
    assert import_binding.AST_STATEMENT_TYPES == running
    assert import_binding.AST_STATEMENT_TYPE_NAMES == {item.__name__ for item in running}
    assert issubclass(import_binding.UnsupportedStatementGrammar, RuntimeError)
