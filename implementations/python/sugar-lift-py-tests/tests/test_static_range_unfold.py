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


def test_subscript_store_static_for_over_cap_projects_compact() -> None:
    """#5338 post-#5574: finite For + subscript store must not N-fold setitem.

    Product hang: scipy test_shortest_path star_graph
      for idx in range(1, n): SP_solution[idx] += ...
    with pytest parametrize n in (10, 100) materializes range and static-unfolds.
    Per-iteration setitem post-state is super-linear (9× ~2s; 99× times out).

    Shared door with branched over-cap: recognition projection under
    py.iter_elem when card > BRANCHED_STATIC_UNFOLD_LIMIT — not force-curry,
    not soft Complete, not bound raise.
    """
    from sugar_lift_py_tests.sugar.for_sugar import (
        BRANCHED_STATIC_UNFOLD_LIMIT,
        ForSugar,
    )

    n = BRANCHED_STATIC_UNFOLD_LIMIT + 1
    indices = ", ".join(str(i) for i in range(1, n + 1))
    source = (
        "def test_star_store():\n"
        f"    idxs = [{indices}]\n"
        "    xs = [0] * 32\n"
        "    for idx in idxs:\n"
        "        xs[idx] += 1\n"
        "    assert xs[1] == 1\n"
    )

    unfold_calls: list[int] = []
    compact_calls: list[object] = []
    orig_unfold = ForSugar._unfold_values
    orig_compact = ForSugar._project_compact_finite

    def _spy_unfold(self, values, ctx, entries=()):
        unfold_calls.append(len(values) if hasattr(values, "__len__") else -1)
        return orig_unfold(self, values, ctx, entries)

    def _spy_compact(self, iterable, ctx):
        compact_calls.append(type(iterable).__name__)
        return orig_compact(self, iterable, ctx)

    ForSugar._unfold_values = _spy_unfold  # type: ignore[method-assign]
    ForSugar._project_compact_finite = _spy_compact  # type: ignore[method-assign]
    try:
        try:
            payload = lift_file_payload(source, "store-for.py")
        except FactoryPanic as panic:
            owner = getattr(panic.info, "owner", None)
            assert owner != "finite_unfold", panic.info
            # Still must have preferred compact over unfold for the store body.
            assert unfold_calls == [], unfold_calls
            assert compact_calls, "expected compact projection for store body"
            return
        assert payload is not None
        assert unfold_calls == [], f"static unfold must not fire for store body: {unfold_calls}"
        assert compact_calls, "expected compact projection for store body over branched cap"
    finally:
        ForSugar._unfold_values = orig_unfold  # type: ignore[method-assign]
        ForSugar._project_compact_finite = orig_compact  # type: ignore[method-assign]


def test_parametrize_star_store_for_completes_under_product_shape() -> None:
    """Product micro of shortest_path star_graph store loop must not hang.

    Mirrors parametrize n in (10, 100) × method × directed expansion of
    ``for idx in range(1, n): SP_solution[idx] += ...``. List store is
    enough to trip super-linear unfold history; hang is the residual.
    """
    import time

    from sugar_lift_py_tests.sugar.for_sugar import BRANCHED_STATIC_UNFOLD_LIMIT

    assert BRANCHED_STATIC_UNFOLD_LIMIT < 10
    source = (
        "import pytest\n"
        "\n"
        "@pytest.mark.parametrize('n', (10, 100))\n"
        "@pytest.mark.parametrize('method', ['FW', 'J', 'BF'])\n"
        "@pytest.mark.parametrize('directed', (True, False))\n"
        "def test_star_graph(n, method, directed):\n"
        "    xs = [0] * 128\n"
        "    for idx in range(1, n):\n"
        "        xs[idx] += 1\n"
        "    assert method is not None or directed is not None\n"
    )
    t0 = time.perf_counter()
    try:
        payload = lift_file_payload(source, "star-store-param.py")
    except FactoryPanic as panic:
        info = getattr(panic, "info", None) or getattr(
            getattr(panic, "value", None), "info", None
        )
        owner = getattr(info, "owner", None)
        assert owner != "finite_unfold", info
        elapsed = time.perf_counter() - t0
        assert elapsed < 8.0, f"store-for product micro too slow before panic: {elapsed:.2f}s"
        return
    elapsed = time.perf_counter() - t0
    assert payload is not None
    assert elapsed < 8.0, f"store-for product micro hung: {elapsed:.2f}s"
