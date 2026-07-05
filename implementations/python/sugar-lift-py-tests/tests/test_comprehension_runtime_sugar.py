from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.outcome import Incomplete


def _reduce_expr(expr: str):
    node = ast.parse(expr, mode="eval").body
    ctx = FactoryBuildContext(filename="comp.py", catalog=default_catalog())
    return ctx.build_body(node, SugarRole.TERM).reduce(ctx)


def test_dict_comprehension_is_typed_runtime_boundary() -> None:
    outcome = _reduce_expr("{x: x + 1 for x in values}")

    assert isinstance(outcome, Incomplete)
    assert "dict comprehension runtime boundary" in outcome.reason
    assert "blame=comp.py:1:0" in outcome.reason


def test_set_comprehension_is_typed_runtime_boundary() -> None:
    outcome = _reduce_expr("{x + 1 for x in values}")

    assert isinstance(outcome, Incomplete)
    assert "set comprehension runtime boundary" in outcome.reason


def test_list_comprehension_keeps_its_owned_runtime_effect() -> None:
    outcome = _reduce_expr("[x + 1 for x in values]")

    assert isinstance(outcome, Incomplete)
    assert "list comprehension runtime boundary" in outcome.reason
