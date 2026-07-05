from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.outcome import Incomplete


def _reduce_expr(expr: str):
    node = ast.parse(expr, mode="eval").body
    ctx = FactoryBuildContext(filename="boolop.py", catalog=default_catalog())
    return ctx.build_body(node, SugarRole.TERM).reduce(ctx)


def test_boolop_expression_is_typed_runtime_boundary() -> None:
    outcome = _reduce_expr("left and right")

    assert isinstance(outcome, Incomplete)
    assert "boolean expression runtime boundary" in outcome.reason
    assert "blame=boolop.py:1:0" in outcome.reason


def test_boolop_or_expression_is_typed_runtime_boundary() -> None:
    outcome = _reduce_expr("left or right")

    assert isinstance(outcome, Incomplete)
    assert "boolean expression runtime boundary" in outcome.reason


def test_assert_boolop_still_uses_assertion_sugar() -> None:
    from sugar_lift_py_tests.factory.literal_call_report import (
        build_literal_call_report,
    )

    report = build_literal_call_report(
        source="def test_flags(a, b):\n    assert a and b\n",
        filename="boolop.py",
        memento_file="boolop.py",
    )

    assert report is not None
    assert report.payload.ir[0].source_warrants[0].role == (
        "python.boolop-assertion-sugar"
    )
