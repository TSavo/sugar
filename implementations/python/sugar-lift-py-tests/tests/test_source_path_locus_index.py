"""Instrument: factory_build volume from full-module ast.walk per Call site.

Product residual after #5425: large modules (test_random, stata) timeout under
factory_build. Profile: BuiltinCalleeUniverseSugar.owns → CalleeUniverseRecognition
→ visible_declarations / _source_path re-walked the entire module AST for every
Call site during factory.select (O(module × sites)).

Replacement architecture:
  - content-keyed ``parsed_locus_index`` (one walk per source)
  - ``locate_parsed_node`` for O(1) locus resolution
  - plain-call leaf short-circuit when the callee cannot authenticate

This instrument stays red while path resolution still pays full-module walks
proportional to site count. Never soft-succeeds Incomplete; bound unchanged.
"""

from __future__ import annotations

import ast
import time

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.recognition.callee_universe import CalleeUniverseRecognition
from sugar_lift_py_tests.recognition.visible_declarations import visible_declarations
from sugar_lift_py_tests.sugar.builtin_callee_universe_sugar import (
    BuiltinCalleeUniverseSugar,
)
from sugar_lift_python_source.source_tables import (
    locate_parsed_node,
    parsed_locus_index,
    parsed_parents,
)


def _large_module(*, statements: int = 400, calls: int = 40) -> str:
    lines = [f"v_{i} = {i}\n" for i in range(statements)]
    lines.append("def probe():\n")
    for i in range(calls):
        lines.append(f"    helper_{i}(v_0)\n")
    lines.append("    return type(v_0)\n")
    return "".join(lines)


def test_parsed_locus_index_is_content_keyed_and_complete() -> None:
    source = "def f(x):\n    return g(x)\n"
    index = parsed_locus_index(source)
    assert index is not None
    tree, _parents = parsed_parents(source)
    assert tree is not None
    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", None)
        col = getattr(node, "col_offset", None)
        if lineno is None or col is None:
            continue
        found = locate_parsed_node(source, type(node), lineno, col)
        assert found is node


def test_source_path_resolution_does_not_full_walk_per_site(monkeypatch) -> None:
    """R: full-module ast.walk must not fire once per Call site.

    Illegal residual shape: each visible_declarations / _source_path call
    walks the Module root. Replacement: locus index built once per source.
    Declaration-local walks (stored_or_deleted_names) are out of scope here.
    """
    source = _large_module(statements=300, calls=30)
    tree = ast.parse(source)
    call_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node, "lineno", 0) >= 0
    ]
    assert len(call_nodes) >= 30

    sites = [
        SourceFragment.from_node(node, "large_mod.py", source=source)
        for node in call_nodes
    ]

    real_walk = ast.walk
    module_root_walks = {"n": 0}

    def counting_walk(node):
        if isinstance(node, ast.Module):
            module_root_walks["n"] += 1
        yield from real_walk(node)

    monkeypatch.setattr(ast, "walk", counting_walk)
    # Warm content-keyed tables under the counter so index build is included.
    parsed_parents.cache_clear()
    parsed_locus_index.cache_clear()

    for site in sites:
        visible_declarations(site)
        CalleeUniverseRecognition.coordinate(site)
        BuiltinCalleeUniverseSugar.owns(site)

    # Legal: parents + locus index (and rare recompute). Residual was ≥1 Module
    # walk per site (≈ len(sites)).
    assert module_root_walks["n"] <= 4, (
        f"source-path resolution walked Module roots {module_root_walks['n']} "
        f"times for {len(sites)} call sites. Illegal shape: full-module "
        f"ast.walk per site during factory.select / "
        f"BuiltinCalleeUniverseSugar.owns. Replacement: parsed_locus_index + "
        f"locate_parsed_node (one walk per source)."
    )


def test_builtin_callee_owns_refuses_unauthenticated_plain_leaves() -> None:
    source = "def f():\n    return helper(1)\n"
    tree = ast.parse(source)
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    site = SourceFragment.from_node(call, "t.py", source=source)
    assert BuiltinCalleeUniverseSugar.owns(site) is False
    assert CalleeUniverseRecognition.coordinate(site) is None


def test_large_definition_factory_select_not_dominated_by_callee_owns() -> None:
    """Product-shaped residual: many Calls inside one def must factory quickly."""
    source = _large_module(statements=200, calls=50)
    tree = ast.parse(source)
    fn = tree.body[-1]
    assert isinstance(fn, ast.FunctionDef)
    ctx = FactoryBuildContext(filename="large_mod.py", catalog=default_catalog())
    t0 = time.perf_counter()
    build_node(fn, filename="large_mod.py", role=SugarRole.DEFINITION, ctx=ctx)
    elapsed = time.perf_counter() - t0
    # Residual was ~1s per Call from owns alone; indexed path is sub-second.
    assert elapsed < 2.0, (
        f"factory of a {50}-call definition took {elapsed:.3f}s; expected "
        f"indexed locus resolution to drain factory.select volume "
        f"(BuiltinCalleeUniverseSugar.owns full-module walk residual)."
    )
