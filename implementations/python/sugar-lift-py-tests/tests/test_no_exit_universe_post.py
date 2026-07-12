from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import RaiseValue, UniverseValue
from sugar_lift_py_tests.ir import ctor, eq, make_var
from sugar_lift_py_tests.outcome import complete_value


def _universe(source: str) -> UniverseValue:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    result = build_node(node, filename="t.py", role=SugarRole.DEFINITION, ctx=ctx)
    value = complete_value(result.sugar.desugar(ctx), owner="test")
    assert isinstance(value, UniverseValue)
    return value


def test_procedure_without_explicit_return_posts_python_none() -> None:
    universe = _universe("def procedure(x):\n    x = 1\n")

    assert universe.post() == eq(make_var("out"), ctor("None", []))


def test_raise_only_body_carries_raise_effect_not_implicit_none() -> None:
    universe = _universe("def reject():\n    raise ValueError()\n")

    assert len(universe.record.statements) == 1
    assert isinstance(universe.record.statements[0], RaiseValue)
    assert universe.record.statements[0].effect.exception_name == "ValueError"
    with pytest.raises(FactoryPanic, match="raise-only"):
        universe.post()


def test_implicit_none_post_is_native_equality_not_call_coordinate() -> None:
    post = _universe("def procedure():\n    pass\n").post()

    assert post == eq(make_var("out"), ctor("None", []))
    assert "call:" not in repr(post)
