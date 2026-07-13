"""ListLiteralSugar: `[1, 2]` reduces each element and the result is a list of them.
Order matters for a list -- the tuple already preserves it. A bare list statement
is discarded (expression statement is support)."""

from __future__ import annotations

import ast

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.outcome import Complete


def test_list_literal_selects_and_reduces_elements() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("[1, 2]", mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    from sugar_lift_py_tests.floor import ListValue

    assert result.audit_row.selected == "ListLiteralSugar"
    assert result.sugar.desugar(ctx) == Complete(
        ListValue((TermValue(1), TermValue(2)))
    )


def test_empty_list_literal_reduces_to_empty_list_value() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("[]", mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    from sugar_lift_py_tests.floor import ListValue

    assert result.audit_row.selected == "ListLiteralSugar"
    assert result.sugar.desugar(ctx) == Complete(ListValue(()))


def test_large_list_literal_reduces_without_recursive_collection() -> None:
    ctx = FactoryBuildContext(filename="generated.py", catalog=default_catalog())
    node = ast.parse("[" + ",".join(str(value) for value in range(1500)) + "]", mode="eval").body
    result = build_node(
        node, filename="generated.py", role=SugarRole.TERM, ctx=ctx
    )

    outcome = result.sugar.desugar(ctx)

    assert isinstance(outcome, Complete)
    assert len(outcome.value.elements) == 1500
    assert outcome.value.elements[0] == TermValue(0)
    assert outcome.value.elements[-1] == TermValue(1499)



def test_list_expression_statement_is_discarded_in_block() -> None:
    block = compose_block("    [1]\n    return 2\n")

    assert block == BlockValue((ReturnValue(TermValue(2)),))
