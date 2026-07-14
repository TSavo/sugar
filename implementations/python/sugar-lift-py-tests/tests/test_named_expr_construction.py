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
from sugar_lift_py_tests.floor import NamedExpressionValue, TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.temporal import TemporalContext


def _site(source: str) -> SourceFragment:
    node = ast.parse(source, mode="eval").body
    return SourceFragment.from_node(node, "vendor.py", source=source)


def _ctx() -> FactoryBuildContext:
    return FactoryBuildContext(
        filename="vendor.py",
        catalog=default_catalog(),
        temporal=TemporalContext.empty(),
    )


def _build(source: str, *, role: SugarRole = SugarRole.TERM):
    ctx = _ctx()
    return build_node(
        _site(source),
        filename="vendor.py",
        role=role,
        ctx=ctx,
    )


@pytest.mark.parametrize(
    "source",
    (
        "(count := len(items))",
        "(flip := step < 0)",
        "(match := find(pattern, value))",
        "(item := 3)",
    ),
)
def test_named_expr_shapes_have_one_term_owner(source: str) -> None:
    built = _build(source)

    assert type(built.sugar).__name__ == "NamedExprSugar"
    candidates = default_catalog().candidates_for(SugarRole.TERM, _site(source))
    assert [candidate.name for candidate in candidates] == ["NamedExprSugar"]


def test_named_expr_returns_rhs_and_carries_the_temporal_rebind() -> None:
    ctx = _ctx()
    outcome = _build("(item := 3)").sugar.desugar(ctx)

    assert outcome == Complete(NamedExpressionValue("item", TermValue(3)))
    assert outcome.value.to_term(owner="test") == TermValue(3).to_term(owner="test")
    assert outcome.extend_scope(ctx).temporal.value_for("item") == TermValue(3)


def test_named_expr_comparison_keeps_rhs_as_the_binding_value() -> None:
    ctx = _ctx()
    outcome = _build("(item := 3) < 4").sugar.desugar(ctx)

    assert isinstance(outcome.value, NamedExpressionValue)
    assert outcome.extend_scope(ctx).temporal.value_for("item") == TermValue(3)


def test_named_expr_statement_role_stays_a_loud_factory_gap() -> None:
    with pytest.raises(FactoryPanic, match="observed=NamedExpr requested=statement"):
        _build("(item := 3)", role=SugarRole.STATEMENT)


def test_named_expr_discriminator_runs_both_process_arms() -> None:
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
from sugar_lift_py_tests.factory.source_fragment import SourceFragment

source = "(item := 3)"
node = ast.parse(source, mode="eval").body
site = SourceFragment.from_node(node, "vendor.py", source=source)
role = SugarRole.TERM if sys.argv[1] == "owned" else SugarRole.STATEMENT
build_node(site, filename="vendor.py", role=role)
"""

    owned = subprocess.run(
        [sys.executable, "-c", script, "owned"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    wrong_role = subprocess.run(
        [sys.executable, "-c", script, "wrong-role"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert owned.returncode == 0, owned.stderr
    assert wrong_role.returncode == 1, wrong_role.stderr
