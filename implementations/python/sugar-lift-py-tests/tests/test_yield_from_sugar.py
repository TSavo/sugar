from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import GeneratorYieldRuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.temporal import TemporalContext


def _yield_from_site(source: str) -> SourceFragment:
    module = ast.parse(source)
    node = next(node for node in ast.walk(module) if isinstance(node, ast.YieldFrom))
    return SourceFragment.from_node(node, "vendor.py", source=source)


def _build(source: str, ctx: FactoryBuildContext | None = None):
    site = _yield_from_site(source)
    return build_node(
        site,
        filename="vendor.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )


@pytest.mark.parametrize(
    "expression",
    (
        "items",
        "flatten(items)",
        "self.items",
        "rows[0]",
        "()",
        "[1, 2]",
    ),
)
def test_yield_from_operand_shapes_have_one_factory_owner(expression: str) -> None:
    built = _build(f"def generate():\n    yield from {expression}\n")

    assert type(built.sugar).__name__ == "YieldFromSugar"


def test_yield_from_is_a_named_generator_protocol_effect() -> None:
    source = "def generate(items):\n    yield from items\n"
    temporal = TemporalContext.empty().bind_value(
        "items", SymbolicValue(make_var("items"))
    )
    ctx = FactoryBuildContext(
        filename="vendor.py",
        catalog=default_catalog(),
        temporal=temporal,
    )
    outcome = _build(source, ctx).sugar.desugar(ctx)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, GeneratorYieldRuntimeEffect)
    assert outcome.effect.witness.operation == ctor(
        "py.generator_yield_from", [make_var("items")]
    )
    assert outcome.effect.witness.operand == make_var("items")


def test_yield_and_yield_from_owners_are_disjoint() -> None:
    source = "def generate():\n    yield 1\n"
    module = ast.parse(source)
    node = next(node for node in ast.walk(module) if isinstance(node, ast.Yield))
    site = SourceFragment.from_node(node, "vendor.py", source=source)
    built = build_node(site, filename="vendor.py", role=SugarRole.TERM)

    assert type(built.sugar).__name__ == "YieldSugar"


def test_yield_from_outside_function_stays_loud() -> None:
    with pytest.raises(FactoryPanic, match="observed=YieldFrom requested=term"):
        _build("yield from items\n")


def test_yield_from_discriminator_runs_both_process_arms() -> None:
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

source = "def generate():\\n    yield from items\\n" if sys.argv[1] == "owned" else "yield from items\\n"
module = ast.parse(source)
node = next(node for node in ast.walk(module) if isinstance(node, ast.YieldFrom))
site = SourceFragment.from_node(node, "vendor.py", source=source)
build_node(site, filename="vendor.py", role=SugarRole.TERM)
"""

    owned = subprocess.run(
        [sys.executable, "-c", script, "owned"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    outside = subprocess.run(
        [sys.executable, "-c", script, "outside"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert owned.returncode == 0, owned.stderr
    assert outside.returncode == 1, outside.stderr
