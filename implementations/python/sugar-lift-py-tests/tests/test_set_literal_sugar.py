"""SetLiteralSugar: `{1, 2}` reduces each element and the result is a set of them.
The set is its reduced elements on the floor -- construction order, no fork."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import SetValue, TermValue
from sugar_lift_py_tests.outcome import Complete


def test_set_literal_selects_and_reduces_elements() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("{1, 2}", mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)

    assert result.audit_row.selected == "SetLiteralSugar"
    assert result.sugar.desugar(ctx) == Complete(
        SetValue((TermValue(1), TermValue(2)))
    )
