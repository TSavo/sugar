from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import GeneratorYieldRuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import GuardedLoopControl, LoopControlValue
from sugar_lift_py_tests.outcome import Incomplete, complete_value


def _statement(source: str, kind: type[ast.stmt]):
    module = ast.parse(source)
    node = next(node for node in ast.walk(module) if isinstance(node, kind))
    site = SourceFragment.from_node(node, "t.py", source=source)
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    result = build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    return complete_value(result.sugar.desugar(ctx), owner="test")


@pytest.mark.parametrize(
    ("source", "kind", "action"),
    [
        ("while flag:\n    break\n", ast.Break, "break"),
        ("for item in items:\n    continue\n", ast.Continue, "continue"),
    ],
)
def test_loop_control_constructs_a_cited_exit(source, kind, action) -> None:
    value = _statement(source, kind)

    assert isinstance(value, LoopControlValue)
    assert value.action == action
    assert f"py.loop_{'exit' if action == 'break' else 'skip'}" in repr(
        value.post_contribution()
    )


def test_guarded_loop_control_keeps_its_guard_and_action() -> None:
    value = _statement("while flag:\n    if flag:\n        break\n", ast.Break)
    guarded = value.guarded("guard")

    assert isinstance(guarded, GuardedLoopControl)
    assert guarded.action == "break"
    assert guarded.guards == ("guard",)


def test_loop_control_outside_a_loop_stays_loud() -> None:
    source = "break\n"
    node = ast.parse(source).body[0]
    site = SourceFragment.from_node(node, "t.py", source=source)

    with pytest.raises(FactoryPanic, match="observed=Break requested=statement"):
        build_node(site, filename="t.py", role=SugarRole.STATEMENT)


def test_yield_is_a_named_generator_protocol_effect() -> None:
    source = "def generate():\n    yield 1\n"
    module = ast.parse(source)
    node = next(node for node in ast.walk(module) if isinstance(node, ast.Yield))
    site = SourceFragment.from_node(node, "t.py", source=source)
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    result = build_node(site, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    outcome = result.sugar.desugar(ctx)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, GeneratorYieldRuntimeEffect)
    assert "py.generator_yield" in outcome.reason


def test_yield_outside_a_function_stays_loud() -> None:
    source = "yield 1\n"
    node = ast.parse(source).body[0].value
    site = SourceFragment.from_node(node, "t.py", source=source)

    with pytest.raises(FactoryPanic, match="observed=Yield requested=term"):
        build_node(site, filename="t.py", role=SugarRole.TERM)
