"""The os.exit argument is factory-built like every other child. An unowned node
inside the argument panics at CONSTRUCTION -- the effect being atomic at reduce
time does not exempt its argument from the audit."""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.effect import OSExitRuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete


def _build(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    return build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx), ctx


def test_os_exit_argument_is_factory_built() -> None:
    result, _ = _build("os.exit(0)\n")
    # ExprSugar wraps the call at the statement role; the body carries the OsSugar.
    sugar = result.sugar.value.sugar
    assert len(sugar.args) == 1


def test_os_exit_still_reduces_to_the_runtime_effect() -> None:
    result, ctx = _build("os.exit(0)\n")
    outcome = result.sugar.desugar(ctx)
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, OSExitRuntimeEffect)


def test_unowned_node_inside_os_exit_argument_panics_at_construction() -> None:
    with pytest.raises(FactoryPanic):
        _build("os.exit(mystery())\n")
