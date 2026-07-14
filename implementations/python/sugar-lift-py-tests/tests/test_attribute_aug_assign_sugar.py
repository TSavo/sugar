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
from sugar_lift_py_tests.floor import ReturnValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var


def _build(source: str):
    node = ast.parse(source).body[0]
    ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
    return build_node(
        node,
        filename="vendor.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )


def test_attribute_add_assign_reads_adds_and_stores_the_same_field() -> None:
    block = compose_block(
        "    obj.value = 2\n" "    obj.value += 3\n" "    return obj.value\n",
        binds={"obj": SymbolicValue(make_var("obj"))},
    )

    returned = next(x for x in block.statements if isinstance(x, ReturnValue))
    assert returned.value == TermValue(5)


def test_attribute_add_assign_has_one_structural_owner() -> None:
    built = _build("obj.value += increment")
    assert type(built.sugar).__name__ == "AttributeAddAssignSugar"
    assert built.sugar.receiver_name == "obj"
    assert built.sugar.field_name == "value"


@pytest.mark.parametrize(
    "source",
    (
        "obj.value |= mask",
        "obj.value -= amount",
        "items[0] += amount",
    ),
)
def test_adjacent_augmented_assignment_partitions_stay_disjoint(source: str) -> None:
    expected = (
        "SubscriptAugAssignSugar"
        if source == "items[0] += amount"
        else "AttributeAugAssignSugar"
    )
    assert type(_build(source).sugar).__name__ == expected


def test_attribute_add_assign_discriminator_runs_both_process_arms() -> None:
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
    "    obj.value = 2\\n"
    "    obj.value += 3\\n"
    "    return obj.value\\n",
    binds={{"obj": SymbolicValue(make_var("obj"))}},
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

    truthful = run(5)
    lying = run(4)
    assert truthful.returncode == 0, truthful.stderr
    assert lying.returncode == 1, lying.stderr
