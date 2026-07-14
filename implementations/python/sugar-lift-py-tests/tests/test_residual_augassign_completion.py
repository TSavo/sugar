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
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import ReturnValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var


def _site(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "vendor.py")


def _build(source: str):
    ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
    return build_node(
        _site(source),
        filename="vendor.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )


@pytest.mark.parametrize(
    ("source", "owner"),
    (
        ("obj.value |= mask", "AttributeAugAssignSugar"),
        ("obj.value -= amount", "AttributeAugAssignSugar"),
        ("items[:stop] |= mask[:stop]", "ResidualSubscriptAugAssignSugar"),
        ("items[1:2] += amount", "SubscriptAugAssignSugar"),
    ),
)
def test_residual_augassign_shapes_have_one_owner(source: str, owner: str) -> None:
    candidates = default_catalog().candidates_for(SugarRole.STATEMENT, _site(source))

    assert [candidate.name for candidate in candidates] == [owner]


@pytest.mark.parametrize(
    ("operator", "expected"),
    (("|=", 7), ("-=", 3)),
)
def test_attribute_augassign_unrolls_read_operator_store(
    operator: str, expected: int
) -> None:
    block = compose_block(
        "    obj.value = 5\n" f"    obj.value {operator} 2\n" "    return obj.value\n",
        binds={"obj": SymbolicValue(make_var("obj"))},
    )

    returned = next(
        value for value in block.statements if isinstance(value, ReturnValue)
    )
    assert returned.value == TermValue(expected)


def test_bitor_subscript_augassign_unrolls_read_operator_store() -> None:
    block = compose_block("    items = [5]\n    items[0] |= 2\n    return items[0]\n")

    assert block.statements == (ReturnValue(TermValue(7)),)


def test_runtime_selected_attribute_receiver_stays_loud() -> None:
    with pytest.raises(FactoryPanic, match="observed=AugAssign requested=statement"):
        _build("items[0].value |= mask")


def test_residual_augassign_discriminator_runs_both_process_arms() -> None:
    tests_dir = Path(__file__).resolve().parent
    src_dir = tests_dir.parent / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(tests_dir), str(src_dir))),
    }
    script = """\
from factory_reduce import compose_block
from sugar_lift_py_tests.floor import ReturnValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var
import sys

block = compose_block(
    "    obj.value = 5\\n"
    "    obj.value |= 2\\n"
    "    return obj.value\\n",
    binds={"obj": SymbolicValue(make_var("obj"))},
)
returned = next(value for value in block.statements if isinstance(value, ReturnValue))
expected = 7 if sys.argv[1] == "truthful" else 5
assert returned.value == TermValue(expected)
"""

    truthful = subprocess.run(
        [sys.executable, "-c", script, "truthful"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    lying = subprocess.run(
        [sys.executable, "-c", script, "lying"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert truthful.returncode == 0, truthful.stderr
    assert lying.returncode == 1, lying.stderr
