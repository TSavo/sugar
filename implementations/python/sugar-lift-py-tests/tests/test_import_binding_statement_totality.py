from __future__ import annotations

import pytest

from sugar_lift_py_tests import import_binding
from sugar_source_tree.tree import SourceFile


class RenamedFutureStatement:
    kind = "RenamedFutureStatement"


def test_import_binding_transfer_rejects_future_statement_variants_loudly() -> None:
    transfer = import_binding._Pass(
        source_cid="blake3-512:" + "0" * 128,
        module_name="fixture",
        module_identities={},
    )
    scope = SourceFile(("pass\n", "fixture.py", "blake3-512:" + "1" * 128)).root

    with pytest.raises(import_binding.UnsupportedStatementVariant):
        transfer.statement(RenamedFutureStatement(), {}, scope)


def test_import_binding_statement_partition_matches_running_grammar() -> None:
    # The adapter owns parser grammar totality.  This pass owns the typed-node
    # statement vocabulary it consumes; a future typed kind reaches the loud
    # arm above rather than silently acquiring lexical authority.
    assert import_binding.TYPED_STATEMENT_KINDS == {
        "FunctionDef",
        "AsyncFunctionDef",
        "ClassDef",
        "Return",
        "Delete",
        "Assign",
        "TypeAlias",
        "AugAssign",
        "AnnAssign",
        "For",
        "AsyncFor",
        "While",
        "If",
        "With",
        "AsyncWith",
        "Match",
        "Raise",
        "Try",
        "TryStar",
        "Assert",
        "Import",
        "ImportFrom",
        "Global",
        "Nonlocal",
        "Expr",
        "Pass",
        "Break",
        "Continue",
    }
    assert issubclass(import_binding.UnsupportedStatementGrammar, RuntimeError)
