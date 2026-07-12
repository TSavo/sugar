from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import ListValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.temporal import TemporalContext


def _starred_fragment(source: str) -> SourceFragment:
    call = ast.parse(source, mode="eval").body
    assert isinstance(call, ast.Call)
    return SourceFragment.from_node(call.args[0], "starred.py")


def test_starred_expression_refuses_runtime_expansion() -> None:
    ctx = FactoryBuildContext(filename="starred.py", catalog=default_catalog())
    body = ctx.build_body(_starred_fragment("f(*args)"), SugarRole.TERM)

    reduce_ctx = ReduceContext.root(owner="starred-test").with_temporal(
        TemporalContext.empty().bind_value("args", SymbolicValue(make_var("args")))
    )
    outcome = body.reduce(reduce_ctx)

    assert isinstance(outcome, Complete)
    assert outcome.value.target_name == "*"
    assert outcome.value.arg_values[0] == SymbolicValue(make_var("args"))


def test_starred_literal_operand_still_refuses_runtime_expansion() -> None:
    ctx = FactoryBuildContext(filename="starred.py", catalog=default_catalog())
    body = ctx.build_body(_starred_fragment("f(*[1, 2])"), SugarRole.TERM)

    outcome = body.reduce(ReduceContext.root(owner="starred-test"))

    assert isinstance(outcome, Complete)
    assert outcome.value.target_name == "*"
    assert isinstance(outcome.value.arg_values[0], ListValue)
    assert [item.value for item in outcome.value.arg_values[0].elements] == [1, 2]


def test_starred_factory_selects_shape_recognizer() -> None:
    ctx = FactoryBuildContext(filename="starred.py", catalog=default_catalog())
    result = build_node(
        _starred_fragment("f(*args)"),
        filename="starred.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )

    assert result.audit_row.selected == "StarredSugar"
