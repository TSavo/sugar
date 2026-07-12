from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import GuardedRaise, RaiseValue, UniverseValue
from sugar_lift_py_tests.ir import ctor, eq, make_var, str_const
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
    assert universe.post() == eq(
        make_var("out"),
        ctor(
            "py.exceptional_exit",
            [str_const("ValueError"), str_const("t.py:2:4")],
        ),
    )


def test_all_paths_raise_cite_guarded_exceptional_exits() -> None:
    universe = _universe(
        "def reject(flag):\n"
        "    if flag:\n"
        "        raise ValueError()\n"
        "    else:\n"
        "        raise TypeError()\n"
    )

    assert universe.record.statements
    assert all(isinstance(entry, GuardedRaise) for entry in universe.record.statements)
    rendered = repr(universe.post())
    assert "py.exceptional_exit" in rendered
    assert "ValueError" in rendered
    assert "TypeError" in rendered
    assert rendered.count("kind='implies'") == 2


def test_unclassified_raise_exit_stays_a_loud_factory_gap() -> None:
    universe = _universe("def reraises():\n    raise\n")

    with pytest.raises(
        FactoryPanic,
        match="unclassified raise exit.*exceptional-exit coordinate",
    ):
        universe.post()


def test_exceptional_exit_bad_twin_is_not_cited() -> None:
    post = _universe("def reject():\n    raise ValueError()\n").post()

    assert "TypeError" not in repr(post)


def test_implicit_none_post_is_native_equality_not_call_coordinate() -> None:
    post = _universe("def procedure():\n    pass\n").post()

    assert post == eq(make_var("out"), ctor("None", []))
    assert "call:" not in repr(post)
