"""The `return <expr>` statement (ReturnSugar): reduce the value, and the result is a
return of it -- a ReturnValue carrying the reduced floor. A block carries that
ReturnValue; bare `return` is a loud factory gap (no invented None)."""

from __future__ import annotations

import ast

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.outcome import Complete, complete_value


def test_return_selects_and_desugars_to_return_value() -> None:
    result = build_node(
        ast.parse("return 5").body[0],
        filename="f.py",
        role=SugarRole.STATEMENT,
    )

    assert result.audit_row.selected == "ReturnSugar"
    assert complete_value(result.sugar.desugar(), owner="return") == ReturnValue(
        TermValue(5)
    )
    assert isinstance(result.sugar.desugar(), Complete)


def test_return_composes_into_block_as_return_value() -> None:
    assert compose_block("    return 5\n") == BlockValue((ReturnValue(TermValue(5)),))
