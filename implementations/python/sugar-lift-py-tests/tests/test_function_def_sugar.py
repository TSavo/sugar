"""FunctionDefSugar: the body becomes a universe. Parameters bind
SymbolicValues (the universe variables), the body reduces to its record under
that scope, and the result is a UniverseValue -- name, formals, record. The
slots are projections of the record: invs are the stated facts, post is
`out == <exit term>`. No harness binds: the def drives the whole spine."""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import UniverseValue
from sugar_lift_py_tests.ir import ctor, eq, make_var, num
from sugar_lift_py_tests.outcome import complete_value


def _universe(source: str) -> UniverseValue:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    result = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    value = complete_value(result.sugar.desugar(ctx), owner="test")
    assert isinstance(value, UniverseValue)
    return value


def test_the_def_binds_its_parameter_and_reduces_the_body() -> None:
    universe = _universe("def A(z):\n    assert z == 1\n    return z\n")
    assert universe.name == "A"
    assert universe.formals == ("z",)
    assert universe.invs() == (eq(make_var("z"), num(1)),)
    assert universe.post() == eq(make_var("out"), make_var("z"))


def test_the_spine_runs_without_harness_binds() -> None:
    universe = _universe(
        "def A(z):\n    y = f(3)\n    assert y == 7\n    return z\n"
    )
    assert universe.invs() == (eq(ctor("call:f", [num(3)]), num(7)),)
    assert universe.post() == eq(make_var("out"), make_var("z"))


def test_concrete_return_posts_the_folded_term() -> None:
    universe = _universe("def A(z):\n    x = 1\n    x = x + 1\n    return x\n")
    assert universe.post() == eq(make_var("out"), num(2))


def test_default_arguments_stay_a_loud_gap() -> None:
    with pytest.raises(FactoryPanic):
        _universe("def A(z=1):\n    return z\n")
