from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.outcome import Incomplete


def _starred_fragment(source: str) -> SourceFragment:
    call = ast.parse(source, mode="eval").body
    assert isinstance(call, ast.Call)
    return SourceFragment.from_node(call.args[0], "starred.py")


def test_starred_expression_refuses_runtime_expansion() -> None:
    ctx = FactoryBuildContext(filename="starred.py", catalog=default_catalog())
    body = ctx.build_body(_starred_fragment("f(*args)"), SugarRole.TERM)

    outcome = body.reduce(ReduceContext.root(owner="starred-test"))

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "starred expression runtime boundary" in outcome.reason
    assert "operand `Name` must be iterated at runtime" in outcome.reason
    assert "typed red" in outcome.reason
    assert "blame=" in outcome.reason


def test_starred_literal_operand_still_refuses_runtime_expansion() -> None:
    ctx = FactoryBuildContext(filename="starred.py", catalog=default_catalog())
    body = ctx.build_body(_starred_fragment("f(*[1, 2])"), SugarRole.TERM)

    outcome = body.reduce(ReduceContext.root(owner="starred-test"))

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "starred expression runtime boundary" in outcome.reason
    assert "operand `List` must be iterated at runtime" in outcome.reason
    assert "typed red" in outcome.reason


def test_starred_factory_selects_shape_recognizer() -> None:
    ctx = FactoryBuildContext(filename="starred.py", catalog=default_catalog())
    result = build_node(
        _starred_fragment("f(*args)"),
        filename="starred.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )

    assert result.audit_row.selected == "StarredSugar"
