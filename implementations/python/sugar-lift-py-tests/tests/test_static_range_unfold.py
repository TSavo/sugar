from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.idd.sugar_witness_instruments import (
    DEFAULT_SUGAR_WITNESS_SEEDS,
)
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


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
    assert sugar.static_elements is None
    assert sugar.curried is True


def test_verified_large_static_range_constructs_concrete_elements() -> None:
    node = ast.parse("for i in range(1000):\n    pass\n").body[0]
    sugar = build_node(node, filename="large.py", role=SugarRole.STATEMENT).sugar

    assert len(sugar.static_elements) == 1000


def test_large_static_range_unfold_is_stack_safe() -> None:
    source = (
        "def test_large():\n"
        "    for i in range(1000):\n"
        "        pass\n"
        "    assert True\n"
    )

    payload = lift_file_payload(source, "large.py")
    assert len(payload.factory_walk) >= 4


def test_static_unfold_cap_still_panics_loudly_above_reviewed_bound() -> None:
    node = ast.parse("for i in range(1025):\n    pass\n").body[0]
    with pytest.raises(
        FactoryPanic, match="at most 1024 concrete loop self-applications"
    ):
        build_node(node, filename="large.py", role=SugarRole.STATEMENT)


def test_literal_tuple_is_structurally_static() -> None:
    node = ast.parse("for i in (1, 2, 3):\n    pass\n").body[0]
    sugar = build_node(node, filename="tuple.py", role=SugarRole.STATEMENT).sugar
    assert len(sugar.static_elements) == 3


def test_large_static_unfold_witness_refutes_wrong_twin(tmp_path: Path) -> None:
    seed = next(
        item
        for item in DEFAULT_SUGAR_WITNESS_SEEDS
        if item.name == "for_large_static_unfold"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "large-static-truthful", seed.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "large-static-lying", seed.lying.source
    )

    assert "ForSugar" in truthful.selected_sugars
    assert truthful.verdict == "sat"
    assert "ForSugar" in lying.selected_sugars
    assert lying.verdict == "unsat"
