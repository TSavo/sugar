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
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Incomplete
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
    node = ast.parse(source).body[0]
    ctx = ctx or _ctx()
    return build_node(
        node,
        filename="vendor.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )


@pytest.mark.parametrize(
    "source",
    (
        "items[index].value = replacement",
        "factory().value = replacement",
        "items[index].value.flags.writeable = False",
        "factory().metadata.name = replacement",
    ),
)
def test_selected_attribute_targets_have_one_factory_owner(source: str) -> None:
    built = _build(source)

    assert type(built.sugar).__name__ == "SelectedAttributeAssignSugar"


def test_runtime_selected_receiver_yields_named_witnessed_effect() -> None:
    ctx = _ctx(
        items=SymbolicValue(make_var("items")),
        index=TermValue(0),
        replacement=TermValue(3),
    )
    built = _build("items[index].value = replacement", ctx)
    outcome = built.sugar.desugar(ctx)

    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "AttributeStoreRuntimeEffect"
    assert outcome.effect.witness.operation.name == "py.setattr"
    assert outcome.effect.witness is not None


def test_existing_name_rooted_attribute_owners_remain_disjoint() -> None:
    assert type(_build("obj.value = replacement").sugar).__name__ == (
        "AttributeAssignSugar"
    )
    assert type(_build("obj.flags.writeable = False").sugar).__name__ == (
        "NestedAttributeAssignSugar"
    )


def test_starred_tuple_unpack_stays_a_loud_factory_gap() -> None:
    with pytest.raises(FactoryPanic, match=r"None => panic"):
        _build("first, *middle, last = values")


def test_selected_attribute_discriminator_runs_both_process_arms() -> None:
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

source = "items[index].value = replacement" if sys.argv[1] == "owned" else "first, *middle, last = values"
node = ast.parse(source).body[0]
ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
build_node(node, filename="vendor.py", role=SugarRole.STATEMENT, ctx=ctx)
"""

    owned = subprocess.run(
        [sys.executable, "-c", script, "owned"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    starred = subprocess.run(
        [sys.executable, "-c", script, "starred"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert owned.returncode == 0, owned.stderr
    assert starred.returncode == 1, starred.stderr
