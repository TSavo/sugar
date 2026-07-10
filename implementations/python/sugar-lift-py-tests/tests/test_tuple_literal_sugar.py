"""TupleLiteralSugar: `(1, 2)` reduces each element and the result is a tuple of
them. The tuple is its reduced elements on the floor -- construction order, no fork."""

from __future__ import annotations

import ast

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue, TupleValue
from sugar_lift_py_tests.outcome import Complete


def test_tuple_literal_selects_and_reduces_elements() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("(1, 2)", mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)

    assert result.audit_row.selected == "TupleLiteralSugar"
    assert result.sugar.desugar(ctx) == Complete(
        TupleValue((TermValue(1), TermValue(2)))
    )


def test_empty_tuple_reduces_to_empty_tuple_value() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("()", mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)

    assert result.audit_row.selected == "TupleLiteralSugar"
    assert result.sugar.desugar(ctx) == Complete(TupleValue(()))


def test_bare_tuple_statement_is_discarded_in_block() -> None:
    outcome = compose_block("    (1, 2)\n    return 2\n")

    assert outcome == BlockValue((ReturnValue(TermValue(2)),))
