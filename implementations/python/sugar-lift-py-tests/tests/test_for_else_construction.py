from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import LoopElseValue, SymbolicValue
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def _site(source: str) -> SourceFragment:
    return SourceFragment.from_node(
        ast.parse(source).body[0], "vendor.py", source=source
    )


def _ctx(**values) -> FactoryBuildContext:
    temporal = TemporalContext.empty()
    for name, value in values.items():
        temporal = temporal.bind_value(name, value)
    return FactoryBuildContext(
        filename="vendor.py",
        catalog=default_catalog(),
        temporal=temporal,
    )


def _build(source: str, ctx: FactoryBuildContext | None = None):
    ctx = ctx or _ctx()
    return build_node(
        _site(source),
        filename="vendor.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )


@pytest.mark.parametrize(
    "source",
    (
        "for item in items:\n    if item:\n        break\nelse:\n    return 1\n",
        "for left, right in items:\n    if left:\n        break\nelse:\n    return 1\n",
    ),
)
def test_for_else_shapes_have_one_owner(source: str) -> None:
    candidates = default_catalog().candidates_for(SugarRole.STATEMENT, _site(source))

    assert [candidate.name for candidate in candidates] == ["ForElseSugar"]


def test_for_else_projects_the_loop_curry_without_break_substitution() -> None:
    source = "for item in items:\n    if item:\n        break\nelse:\n    return 1\n"
    ctx = _ctx(items=SymbolicValue(make_var("items")))
    value = complete_value(_build(source, ctx).sugar.desugar(ctx), owner="test")

    assert isinstance(value, LoopElseValue)
    assert value.no_break_formula == atomic(
        "py.loop.no_break", [value.loop_scope.callsite.term]
    )
    assert value.loop_scope.callsite.parameters[-1] == "__break__"


def test_starred_for_else_target_remains_a_loud_factory_gap() -> None:
    source = "for head, *rest in items:\n    break\nelse:\n    return 1\n"
    with pytest.raises(FactoryPanic, match="observed=For requested=statement"):
        _build(source)


def test_for_else_discriminator_runs_both_process_arms() -> None:
    tests_dir = Path(__file__).resolve().parent
    src_dir = tests_dir.parent / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(tests_dir), str(src_dir))),
    }
    script = """\
import ast
import sys
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node

owned = "for item in items:\\n    if item:\\n        break\\nelse:\\n    return 1\\n"
bad = "for head, *rest in items:\\n    break\\nelse:\\n    return 1\\n"
source = owned if sys.argv[1] == "owned" else bad
build_node(ast.parse(source).body[0], filename="vendor.py", role=SugarRole.STATEMENT)
"""

    owned = subprocess.run(
        [sys.executable, "-c", script, "owned"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    bad = subprocess.run(
        [sys.executable, "-c", script, "bad"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert owned.returncode == 0, owned.stderr
    assert bad.returncode == 1, bad.stderr
