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
from sugar_lift_py_tests.floor import (
    ScopeRebind,
    SupportValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.temporal import TemporalContext


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
        ast.parse(source).body[0],
        filename="vendor.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )


@pytest.mark.parametrize(
    "source",
    (
        "self.value: int | None = None",
        "self.value: Callable | None = replacement",
        "self.value: Iterator[list[str]] | list[list[int]] = []",
        "self.value: int | None",
        "self.value: list[int]",
    ),
)
def test_attribute_annassign_shapes_have_one_factory_owner(source: str) -> None:
    built = _build(source)

    assert type(built.sugar).__name__ == "AttributeAnnAssignSugar"


def test_union_annotation_is_factory_built_by_the_annotation_owner() -> None:
    built = _build("self.value: int | None = None")

    assert type(built.sugar.annotation.sugar).__name__ == "AnnotationUnionSugar"


def test_valued_attribute_annassign_rebinds_the_field() -> None:
    ctx = _ctx(self=SymbolicValue(make_var("self")))
    outcome = _build("self.value: int | None = 3", ctx).sugar.desugar(ctx)

    assert outcome == Complete(ScopeRebind("self.value", TermValue(3)))


def test_annotation_only_attribute_annassign_is_support_without_a_store() -> None:
    outcome = _build("self.value: list[int]").sugar.desugar(_ctx())

    assert outcome == Complete(SupportValue())


def test_subscript_annassign_remains_a_loud_factory_gap() -> None:
    with pytest.raises(FactoryPanic, match="observed=AnnAssign requested=statement"):
        _build("items[0]: int = 1")


def test_attribute_annassign_discriminator_runs_both_process_arms() -> None:
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

source = "self.value: int | None = None" if sys.argv[1] == "owned" else "items[0]: int = 1"
build_node(ast.parse(source).body[0], filename="vendor.py", role=SugarRole.STATEMENT)
"""

    owned = subprocess.run(
        [sys.executable, "-c", script, "owned"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    subscript = subprocess.run(
        [sys.executable, "-c", script, "subscript"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert owned.returncode == 0, owned.stderr
    assert subscript.returncode == 1, subscript.stderr
