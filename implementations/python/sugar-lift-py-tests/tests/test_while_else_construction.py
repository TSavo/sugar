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
        "while ready:\n    if ready:\n        break\nelse:\n    return 1\n",
        "while ready:\n    pass\nelse:\n    return 1\n",
    ),
)
def test_while_else_shapes_have_one_owner(source: str) -> None:
    candidates = default_catalog().candidates_for(SugarRole.STATEMENT, _site(source))

    assert [candidate.name for candidate in candidates] == ["WhileElseSugar"]


def test_while_else_projects_the_loop_curry_without_break_substitution() -> None:
    source = "while ready:\n    if ready:\n        break\nelse:\n    return 1\n"
    ctx = _ctx(ready=SymbolicValue(make_var("ready")))
    value = complete_value(_build(source, ctx).sugar.desugar(ctx), owner="test")

    assert isinstance(value, LoopElseValue)
    assert value.no_break_formula == atomic(
        "py.loop.no_break", [value.loop_scope.callsite.term]
    )
    assert value.loop_scope.callsite.parameters[-1] == "__break__"


def test_nested_loop_break_is_not_owned_by_outer_while_else() -> None:
    direct_break = (
        "while ready:\n" "    if ready:\n" "        break\n" "else:\n" "    return 1\n"
    )
    nested_break = (
        "while ready:\n"
        "    for inner in ready:\n"
        "        break\n"
        "else:\n"
        "    return 1\n"
    )

    assert _build(direct_break).sugar.has_break is True
    assert _build(nested_break).sugar.has_break is False


def test_empty_orelse_while_stays_with_while_sugar() -> None:
    source = "while ready:\n    pass\n"
    candidates = default_catalog().candidates_for(SugarRole.STATEMENT, _site(source))
    assert [candidate.name for candidate in candidates] == ["WhileSugar"]


def test_for_else_is_not_owned_by_while_else() -> None:
    source = "for item in items:\n    break\nelse:\n    return 1\n"
    candidates = default_catalog().candidates_for(SugarRole.STATEMENT, _site(source))
    assert [candidate.name for candidate in candidates] == ["ForElseSugar"]


def test_while_else_discriminator_runs_both_process_arms() -> None:
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

owned = "while ready:\\n    if ready:\\n        break\\nelse:\\n    return 1\\n"
# starred for-else remains an unowned loud factory gap
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
