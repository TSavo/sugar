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


def _sugar_names(sugar) -> list[str]:
    names = [type(sugar).__name__]
    for child in sugar.walk_children():
        child_sugar = getattr(child, "sugar", None)
        if child_sugar is not None:
            names.extend(_sugar_names(child_sugar))
    return names


@pytest.mark.parametrize(
    "expression",
    (
        "(left < right) | (left >= right)",
        "(left == right) | (isna(left) & isna(right))",
        "left | right",
    ),
)
def test_statement_gateway_marks_runtime_bit_or_without_source_text(
    expression: str,
) -> None:
    node = ast.parse(f"def f(left, right):\n    return {expression}\n").body[0]
    ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
    result = build_node(
        node,
        filename="vendor.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )

    assert "RuntimeBitwiseOpSugar" in _sugar_names(result.sugar)


def test_statement_gateway_keeps_annotation_bit_or_on_annotation_owner() -> None:
    node = ast.parse("value: int | str = value\n").body[0]
    ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
    result = build_node(
        node,
        filename="vendor.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )

    names = _sugar_names(result.sugar)
    assert "AnnotationUnionSugar" in names
    assert "RuntimeBitwiseOpSugar" not in names


def test_bare_sourceless_bit_or_stays_loud() -> None:
    node = ast.parse("left | right", mode="eval").body
    ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())

    with pytest.raises(FactoryPanic, match=r"None => panic"):
        build_node(
            node,
            filename="vendor.py",
            role=SugarRole.TERM,
            ctx=ctx,
        )


def test_runtime_context_discriminator_runs_both_process_arms() -> None:
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
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog

source = "def f(left, right):\\n    return left | right\\n"
node = ast.parse(source).body[0] if sys.argv[1] == "runtime" else ast.parse("left | right", mode="eval").body
role = SugarRole.STATEMENT if sys.argv[1] == "runtime" else SugarRole.TERM
ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
build_node(node, filename="vendor.py", role=role, ctx=ctx)
"""

    runtime = subprocess.run(
        [sys.executable, "-c", script, "runtime"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    unknown = subprocess.run(
        [sys.executable, "-c", script, "unknown"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert runtime.returncode == 0, runtime.stderr
    assert unknown.returncode == 1, unknown.stderr
