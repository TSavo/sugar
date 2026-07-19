from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import sugar_lift_py_tests.sugar.for_sugar as for_sugar_module
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import FactoryWalkStatus
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.idd.sugar_witness_instruments import (
    DEFAULT_SUGAR_WITNESS_SEEDS,
)
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_for_sugar_has_no_inline_ast_shape_classifiers() -> None:
    source = inspect.getsource(for_sugar_module)

    assert "ast." not in source
    assert "_static_iterable_elements" not in source
    assert "OwnScopeStores" not in source


def test_static_range_unfolds_mid_loop_first_binding_across_iterations() -> None:
    source = (
        "def f():\n"
        "    total = 0\n"
        "    for comp in range(0, 3):\n"
        "        if comp == 0:\n"
        "            first = 7\n"
        "        total += first\n"
        "    return total\n"
    )
    payload = lift_file_payload(source, "static.py")
    assert payload.effects == []


def test_symbolic_range_keeps_deferred_curry() -> None:
    node = ast.parse("for i in range(stop):\n    if i:\n        break\n").body[0]
    sugar = build_node(node, filename="symbolic.py", role=SugarRole.STATEMENT).sugar
    assert type(sugar.iterable.sugar).__name__ == "CallSugar"
    assert sugar.curried is True


def test_verified_large_static_range_uses_call_sugar_recognizer() -> None:
    node = ast.parse("for i in range(1000):\n    pass\n").body[0]
    sugar = build_node(node, filename="large.py", role=SugarRole.STATEMENT).sugar

    assert type(sugar.iterable.sugar).__name__ == "CallSugar"


def test_large_static_range_unfold_is_stack_safe() -> None:
    source = (
        "def test_large():\n"
        "    for i in range(1000):\n"
        "        pass\n"
        "    assert True\n"
    )

    payload = lift_file_payload(source, "large.py")
    assert len(payload.factory_walk) >= 4


def test_large_static_range_projects_compact_not_finite_unfold() -> None:
    """Over-cap range uses CallSiteValue projection — no finite_unfold panic."""
    source = (
        "def f():\n"
        "    total = 0\n"
        "    for i in range(1025):\n"
        "        total = 7\n"
        "    return total\n"
    )
    try:
        payload = lift_file_payload(source, "large.py")
    except FactoryPanic as panic:
        assert panic.value.info.owner != "finite_unfold", panic.value.info
        return
    assert len(payload.factory_walk) >= 4


def test_literal_tuple_uses_tuple_literal_recognizer() -> None:
    node = ast.parse("for i in (1, 2, 3):\n    pass\n").body[0]
    sugar = build_node(node, filename="tuple.py", role=SugarRole.STATEMENT).sugar
    assert type(sugar.iterable.sugar).__name__ == "TupleLiteralSugar"


def test_branched_static_for_over_cap_projects_compact_not_force_curried() -> None:
    """#5338: over-cap finite branch work projects compactly, not force-curry.

    Microbench before BRANCHED_STATIC_UNFOLD_LIMIT: 14×abs+if+in ~113s.
    Shared door: recognition projection under py.iter_elem (no force_curry).
    """
    from sugar_lift_py_tests.sugar.for_sugar import BRANCHED_STATIC_UNFOLD_LIMIT

    funcs = ", ".join(["abs"] * (BRANCHED_STATIC_UNFOLD_LIMIT + 6))
    source = (
        "def test_branched():\n"
        f"    funcs = ({funcs})\n"
        "    probfuncs = (abs, abs)\n"
        "    for func in funcs:\n"
        "        if func in probfuncs:\n"
        "            x = 1\n"
        "        else:\n"
        "            x = 2\n"
        "        out = func(x)\n"
        "    assert True\n"
    )
    # Must not raise finite_unfold; construction may advance to another owner.
    try:
        payload = lift_file_payload(source, "branched-for.py")
    except FactoryPanic as panic:
        assert panic.value.info.owner != "finite_unfold", panic.value.info
        return
    assert payload is not None
