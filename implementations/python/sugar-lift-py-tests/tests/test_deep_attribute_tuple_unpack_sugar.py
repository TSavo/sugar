from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest
from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import ReturnValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.nested_attribute_assign_sugar import (
    NestedAttributeAssignSugar,
)
from sugar_lift_py_tests.sugar.tuple_unpack_assign_sugar import (
    TupleUnpackAssignSugar,
)


def _build(source: str):
    node = ast.parse(source).body[0]
    ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
    return build_node(
        node,
        filename="vendor.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )


def test_deep_attribute_tuple_unpack_rebinds_each_projected_leaf() -> None:
    block = compose_block(
        "    left.index.name, right.columns.name = (True, False)\n"
        "    return right.columns.name\n",
        binds={
            "left": SymbolicValue(make_var("left")),
            "right": SymbolicValue(make_var("right")),
        },
    )

    returned = next(
        entry for entry in block.statements if isinstance(entry, ReturnValue)
    )
    assert isinstance(returned.value, FalseBoolLiteralSugar)


def test_deep_attribute_tuple_unpack_uses_the_existing_linear_store_owner() -> None:
    built = _build("left.index.name, right.columns.name = values")

    assert isinstance(built.sugar, TupleUnpackAssignSugar)
    assert [type(store.sugar) for store in built.sugar.stores] == [
        NestedAttributeAssignSugar,
        NestedAttributeAssignSugar,
    ]
    assert [store.sugar.path for store in built.sugar.stores] == [
        ("left", "index", "name"),
        ("right", "columns", "name"),
    ]


@pytest.mark.parametrize(
    "source",
    (
        "factory().index.name, right.columns.name = values",
        "items[0].index.name, right.columns.name = values",
    ),
)
def test_call_and_subscript_rooted_unpack_leaves_stay_loud(source: str) -> None:
    with pytest.raises(FactoryPanic, match=r"None => panic"):
        _build(source)


def test_deep_attribute_tuple_unpack_discriminator_runs_both_process_arms() -> None:
    tests_dir = Path(__file__).resolve().parent
    src_dir = tests_dir.parent / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(tests_dir), str(src_dir))),
    }

    def run(expected: str) -> subprocess.CompletedProcess[str]:
        script = f"""\
from factory_reduce import compose_block
from sugar_lift_py_tests.floor import ReturnValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

block = compose_block(
    "    left.index.name, right.columns.name = (True, False)\\n"
    "    return right.columns.name\\n",
    binds={{
        "left": SymbolicValue(make_var("left")),
        "right": SymbolicValue(make_var("right")),
    }},
)
returned = next(x for x in block.statements if isinstance(x, ReturnValue))
assert isinstance(returned.value, {expected})
"""
        return subprocess.run(
            [sys.executable, "-c", script],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    truthful = run("FalseBoolLiteralSugar")
    lying = run("TrueBoolLiteralSugar")
    assert truthful.returncode == 0, truthful.stderr
    assert lying.returncode == 1, lying.stderr
