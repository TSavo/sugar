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
from sugar_lift_py_tests.floor import ReturnValue, TermValue
from sugar_lift_py_tests.sugar.subscript_assign_sugar import SubscriptAssignSugar
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


def test_subscript_tuple_unpack_threads_each_projected_store() -> None:
    block = compose_block(
        "    left = [0, 0]\n"
        "    right = [0, 0]\n"
        "    left[0], right[1] = (2, 3)\n"
        "    return left[0] + right[1]\n"
    )

    returned = next(
        entry for entry in block.statements if isinstance(entry, ReturnValue)
    )
    assert returned.value == TermValue(5)


def test_subscript_tuple_unpack_reuses_the_existing_store_owner() -> None:
    built = _build("labels[i], shape[i] = pair")

    assert isinstance(built.sugar, TupleUnpackAssignSugar)
    assert [type(store.sugar) for store in built.sugar.stores] == [
        SubscriptAssignSugar,
        SubscriptAssignSugar,
    ]
    assert [store.sugar.receiver_coordinate for store in built.sugar.stores] == [
        "labels",
        "shape",
    ]
    # One-door construction: structural fields are always present (empty for
    # non-nested leaves). A missing-arg TypeError is bare residual, not green.
    for store in built.sugar.stores:
        assert store.sugar.structural_root is None
        assert store.sugar.structural_root_coordinate is None
        assert store.sugar.structural_indices == ()


def test_rot90_style_axes_swap_unpack_constructs_subscript_stores() -> None:
    """numpy.lib.rot90: ``(axes_list[a], axes_list[b]) = (axes_list[b], axes_list[a])``.

    Pre-fix residual bare TypeError: unpack rebuilt SubscriptAssignSugar without
    structural_* fields after they became required. Construction must succeed;
    further reduction may advance to a named FactoryPanic, never a bare TypeError.
    """
    built = _build(
        "(axes_list[axes[0]], axes_list[axes[1]]) = (axes_list[axes[1]], axes_list[axes[0]])"
    )
    assert isinstance(built.sugar, TupleUnpackAssignSugar)
    assert all(
        isinstance(store.sugar, SubscriptAssignSugar) for store in built.sugar.stores
    )
    for store in built.sugar.stores:
        assert store.sugar.receiver_coordinate == "axes_list"
        assert store.sugar.structural_root is None
        assert store.sugar.structural_indices == ()


def test_chained_subscript_targets_construct_through_the_one_door() -> None:
    """Multi-target ``a[i] = b[j] = value`` must not bare-TypeError on structural_*.

    Pre-fix residual rebuilt ``SubscriptAssignSugar`` without the required
    nested-path fields; the one-door ``from_target`` constructor ends that class.
    """
    built = _build("left[0] = right[0] = value")
    from sugar_lift_py_tests.sugar.chained_assign_sugar import ChainedAssignSugar

    assert isinstance(built.sugar, ChainedAssignSugar)
    assert [type(store.sugar) for store in built.sugar.stores] == [
        SubscriptAssignSugar,
        SubscriptAssignSugar,
    ]
    for store in built.sugar.stores:
        assert store.sugar.structural_root is None
        assert store.sugar.structural_indices == ()


@pytest.mark.parametrize(
    "source",
    (
        # Chained multi-target with a tuple leaf stays unowned (not ChainedAssign).
        "x = y = (a, b) = z",
        # Dynamic attribute root is still outside NestedAttribute / AttributeAssign.
        "f().x = g().y = value",
    ),
)
def test_adjacent_unowned_assignment_shapes_stay_loud(source: str) -> None:
    with pytest.raises(FactoryPanic, match=r"None => panic"):
        _build(source)


def test_subscript_tuple_unpack_discriminator_runs_both_process_arms() -> None:
    tests_dir = Path(__file__).resolve().parent
    src_dir = tests_dir.parent / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(tests_dir), str(src_dir))),
    }

    def run(expected: int) -> subprocess.CompletedProcess[str]:
        script = f"""\
from factory_reduce import compose_block
from sugar_lift_py_tests.floor import ReturnValue, TermValue

block = compose_block(
    "    left = [0, 0]\\n"
    "    right = [0, 0]\\n"
    "    left[0], right[1] = (2, 3)\\n"
    "    return left[0] + right[1]\\n"
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
    lying = run(6)
    assert truthful.returncode == 0, truthful.stderr
    assert lying.returncode == 1, lying.stderr
