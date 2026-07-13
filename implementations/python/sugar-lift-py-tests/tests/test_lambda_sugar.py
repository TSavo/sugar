"""LambdaSugar: lambda params: body is a LambdaCallable with in-source body.

Simple positional names only. Defaults / *args / **kwargs stay loud gaps.
"""

from __future__ import annotations

import ast

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import LambdaCallable, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, make_var, num, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.lambda_sugar import LambdaSugar


def _site(expr: str):
    node = ast.parse(expr, mode="eval").body
    return SourceFragment.from_node(node, "t.py")


def test_lambda_carries_param_and_in_source_body() -> None:
    """(1) lambda x: x builds LambdaCallable with param x and a body."""
    value = reduce_value("lambda x: x")
    assert isinstance(value, LambdaCallable)
    assert value.parameters == ("x",)
    assert value.parameter == "x"
    assert value.body is not None
    # Body is a SugarBody that reduces to the free param coordinate.
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    from dataclasses import replace
    from sugar_lift_py_tests.temporal import TemporalContext

    temporal = TemporalContext.empty().bind_value("x", SymbolicValue(make_var("x")))
    scoped = replace(ctx, temporal=temporal)
    reduced = complete_value(value.body.reduce(scoped), owner="lambda-body")
    assert reduced == SymbolicValue(make_var("x"))
    assert value.to_term(owner="t") == ctor("python:lambda", [str_const("x")])


def test_body_and_param_discriminate() -> None:
    """(2) Different body or param name => different value."""
    identity = reduce_value("lambda x: x")
    plus_one = reduce_value("lambda x: x + 1")
    other_param = reduce_value("lambda y: y")

    assert isinstance(identity, LambdaCallable)
    assert isinstance(plus_one, LambdaCallable)
    assert isinstance(other_param, LambdaCallable)

    assert identity.parameters == ("x",)
    assert other_param.parameters == ("y",)
    assert identity.parameters != other_param.parameters

    # Different body sugars -- not the same callable value.
    assert identity != plus_one
    assert identity.body != plus_one.body

    # Under free param, identity body is x; plus_one is x+1.
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    from dataclasses import replace
    from sugar_lift_py_tests.temporal import TemporalContext

    temporal = TemporalContext.empty().bind_value("x", SymbolicValue(make_var("x")))
    scoped = replace(ctx, temporal=temporal)
    id_val = complete_value(identity.body.reduce(scoped), owner="id")
    plus_val = complete_value(plus_one.body.reduce(scoped), owner="plus")
    assert id_val == SymbolicValue(make_var("x"))
    # Binary + over free vars is a term coordinate.
    assert id_val != plus_val


def test_owns_simple_lambda_not_function_def_or_defaults() -> None:
    """(3) owns simple-param Lambda; not FunctionDef; defaults/vararg loud."""
    assert LambdaSugar.owns(_site("lambda x: x")) is True
    assert LambdaSugar.owns(_site("lambda x, y: x")) is True
    assert LambdaSugar.owns(_site("lambda: 1")) is True
    assert LambdaSugar.owns(_site("lambda x=1: x")) is False
    assert LambdaSugar.owns(_site("lambda *a: a")) is False
    assert LambdaSugar.owns(_site("lambda **k: k")) is False

    # FunctionDef is a different observed kind.
    fn_site = SourceFragment.from_node(
        ast.parse("def f(x):\n    return x\n").body[0], "t.py"
    )
    assert LambdaSugar.owns(fn_site) is False

    catalog = default_catalog()
    names = [
        c.name for c in catalog.candidates_for(SugarRole.TERM, _site("lambda x: x"))
    ]
    assert "LambdaSugar" in names


def test_defaulted_param_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("lambda x=1: x", mode="eval").body
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    assert raised.value.info.observed == "Lambda"


def test_vararg_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("lambda *a: a", mode="eval").body
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    assert raised.value.info.observed == "Lambda"


def test_multi_param_simple_names_carry_all_formals() -> None:
    value = reduce_value("lambda x, y: x")
    assert isinstance(value, LambdaCallable)
    assert value.parameters == ("x", "y")
    assert value.to_term(owner="t") == ctor(
        "python:lambda", [str_const("x"), str_const("y")]
    )
