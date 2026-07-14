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
from sugar_lift_py_tests.floor import ReturnValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.sugar.attribute_assign_sugar import AttributeAssignSugar
from sugar_lift_py_tests.sugar.chained_assign_sugar import ChainedAssignSugar
from sugar_lift_py_tests.sugar.subscript_assign_sugar import SubscriptAssignSugar


def _build(source: str):
    node = ast.parse(source).body[0]
    ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
    return build_node(
        node,
        filename="vendor.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )


def test_chained_mixed_targets_thread_the_same_rhs_through_each_store() -> None:
    block = compose_block(
        "    right = [0]\n"
        "    left.value = right[0] = alias = 5\n"
        "    return left.value + right[0] + alias\n",
        binds={"left": SymbolicValue(make_var("left"))},
    )

    returned = next(
        entry for entry in block.statements if isinstance(entry, ReturnValue)
    )
    assert returned.value == TermValue(15)


def test_chained_mixed_targets_reuse_existing_store_owners() -> None:
    built = _build("obj.value = items[0] = alias = result")

    assert isinstance(built.sugar, ChainedAssignSugar)
    assert [type(store.sugar).__name__ for store in built.sugar.stores] == [
        AttributeAssignSugar.__name__,
        SubscriptAssignSugar.__name__,
        "ChainedNameStore",
    ]


@pytest.mark.parametrize(
    "source",
    (
        "factory().value = alias = result",
        "left = (right, other) = result",
    ),
)
def test_adjacent_chained_target_shapes_stay_loud(source: str) -> None:
    with pytest.raises(FactoryPanic, match=r"None => panic"):
        _build(source)


def test_chained_mixed_target_discriminator_runs_both_process_arms() -> None:
    tests_dir = Path(__file__).resolve().parent
    src_dir = tests_dir.parent / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(tests_dir), str(src_dir))),
    }

    def run(expected: int) -> subprocess.CompletedProcess[str]:
        script = f"""\
from factory_reduce import compose_block
from sugar_lift_py_tests.floor import ReturnValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var

block = compose_block(
    "    right = [0]\\n"
    "    left.value = right[0] = alias = 5\\n"
    "    return left.value + right[0] + alias\\n",
    binds={{"left": SymbolicValue(make_var("left"))}},
)
returned = next(x for x in block.statements if isinstance(x, ReturnValue))
assert returned.value == TermValue({expected})
"""
        return subprocess.run(
            [sys.executable, "-c", script],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    truthful = run(15)
    lying = run(14)
    assert truthful.returncode == 0, truthful.stderr
    assert lying.returncode == 1, lying.stderr
