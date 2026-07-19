from __future__ import annotations

import ast
import inspect
from pathlib import Path

import sugar_lift_py_tests.sugar.for_sugar as for_sugar_module
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node
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


def test_large_static_range_projects_the_callable_loop_floor() -> None:
    source = (
        "def f():\n"
        "    total = 0\n"
        "    for i in range(1025):\n"
        "        total = 7\n"
        "    return total\n"
    )

    payload = lift_file_payload(source, "large.py")

    assert payload.effects == []
    assert any(
        row.output == "ForSugar" and row.status == FactoryWalkStatus.WARRANTED
        for row in payload.factory_walk
    )
    assert "call:loop:large.py:3:4" in str(payload.ir[0].post)


def test_literal_tuple_uses_tuple_literal_recognizer() -> None:
    node = ast.parse("for i in (1, 2, 3):\n    pass\n").body[0]
    sugar = build_node(node, filename="tuple.py", role=SugarRole.STATEMENT).sugar
    assert type(sugar.iterable.sugar).__name__ == "TupleLiteralSugar"


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


def test_branched_static_for_over_callable_tuple_force_curries_not_hangs() -> None:
    """#5323: ForSugar static unfold × If × InOp over 14 callables must not hang.

    Microbench before BRANCHED_STATIC_UNFOLD_LIMIT: 14×abs+if+in ~113s;
    after force-curry above 8 branched iterations: ~1.5s.
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
    payload = lift_file_payload(source, "branched-for.py")
    assert payload.effects == []
    assert any(
        row.output == "ForSugar" and row.status == FactoryWalkStatus.WARRANTED
        for row in payload.factory_walk
    )
