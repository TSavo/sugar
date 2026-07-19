"""Instrument: factory_build / factory.select volume residual.

Product residual after #5429 (parsed_locus_index): large modules
(test_random, test_randomstate, stata) still timeout under factory_build with
tip ``Call|factory.select``. Profile supersedes the AST-walk claim:

  BuiltinCalleeUniverseSugar.owns → CalleeUniverseRecognition.coordinate →
  imported_call_identity paid full import/symtable work for every Attribute
  Call with a Name receiver (``random.multinomial``, ``prng.tomaxint``, …)
  even when the attr leaf cannot authenticate. Plus uncached
  ``symtable.symtable`` per ``lexical_function_bindings`` call.

Replacement architecture:
  - content-keyed ``parsed_locus_index`` (one AST walk per source) — #5429
  - content-keyed ``source_symtable`` (one symbol table per source)
  - Attribute import-identity only for registered authenticated leaves
  - class-attribute converter aliases stay on ``_method_coordinate`` only
  - owns: one coordinate resolution (no double-pay)

This instrument stays red while non-leaf Attribute Calls still pay
imported_call_identity, or while factory.select of product-shaped method
volume exceeds the wall bound. Never soft-succeeds Incomplete; bound unchanged.
"""

from __future__ import annotations

import ast
import time

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.recognition import callee_universe as callee_universe_mod
from sugar_lift_py_tests.recognition.callee_universe import CalleeUniverseRecognition
from sugar_lift_py_tests.recognition.visible_declarations import visible_declarations
from sugar_lift_py_tests.sugar.builtin_callee_universe_sugar import (
    BuiltinCalleeUniverseSugar,
)
from sugar_lift_python_source.source_tables import (
    locate_parsed_node,
    parsed_locus_index,
    parsed_parents,
    source_symtable,
)


def _large_module(*, statements: int = 400, calls: int = 40) -> str:
    lines = [f"v_{i} = {i}\n" for i in range(statements)]
    lines.append("def probe():\n")
    for i in range(calls):
        lines.append(f"    helper_{i}(v_0)\n")
    lines.append("    return type(v_0)\n")
    return "".join(lines)


def _product_shaped_method_module(*, statements: int = 200, methods: int = 80) -> str:
    """Many ``mod.method()`` Attribute Calls — residual factory.select shape."""

    lines = [f"v_{i} = {i}\n" for i in range(statements)]
    lines.append("import random_mod as random\n")
    lines.append("class TestDist:\n")
    for i in range(methods):
        lines.append(f"    def test_m_{i}(self):\n")
        lines.append(f"        prng = random.RandomState({i})\n")
        lines.append(f"        x = prng.multinomial(20, [1 / 6.0] * 6)\n")
        lines.append(f"        y = prng.tomaxint(10)\n")
        lines.append(f"        assert random.isscalar(x) or True\n")
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


def test_nonleaf_attribute_calls_skip_imported_call_identity(monkeypatch) -> None:
    """R: non-leaf Attribute Calls must not pay imported_call_identity.

    Illegal residual after #5429: every ``prng.multinomial`` / ``random.X``
    still resolved full import identity during factory.select. Replacement:
    only registered authenticated attribute leaves enter that path; class
    aliases stay on method-coordinate only.
    """
    source = _product_shaped_method_module(statements=50, methods=40)
    tree = ast.parse(source)
    sites = [
        SourceFragment.from_node(node, "product_shape.py", source=source)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]
    assert len(sites) >= 100

    real_imported = callee_universe_mod.imported_call_identity
    nonleaf_imported = {"n": 0}

    def counting_imported(site):
        target = site.call_target_name() if site is not None else None
        receiver = site.call_receiver() if site is not None else None
        if (
            receiver is not None
            and receiver.observed == "Name"
            and target is not None
            and target not in callee_universe_mod._IMPORTED_ATTRIBUTE_LEAVES
        ):
            nonleaf_imported["n"] += 1
        return real_imported(site)

    monkeypatch.setattr(
        callee_universe_mod, "imported_call_identity", counting_imported
    )

    for site in sites:
        CalleeUniverseRecognition.coordinate(site)
        BuiltinCalleeUniverseSugar.owns(site)

    assert nonleaf_imported["n"] == 0, (
        f"imported_call_identity ran {nonleaf_imported['n']} times for "
        f"non-leaf Attribute Calls across {len(sites)} sites. Illegal shape: "
        f"factory.select pays full import identity for random.X / module.Y. "
        f"Replacement: leaf-gated Attribute path + method-coordinate aliases."
    )


def test_source_symtable_is_content_keyed_once_per_source() -> None:
    source = "def f(x):\n    type = x\n    return type(1)\n"
    source_symtable.cache_clear()
    first = source_symtable(source)
    second = source_symtable(source)
    assert first is not None
    assert first is second
    info = source_symtable.cache_info()
    assert info.maxsize is not None
    assert info.hits >= 1


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


def test_product_method_volume_factory_select_wall() -> None:
    """R: many non-auth Attribute Calls must not dominate factory.select wall.

    Mirrors test_random / test_randomstate method density after locus index.
    Residual shape: owns paid ~20ms/site import identity; product timed out
    under factory_build with tip Call|factory.select.
    """
    source = _product_shaped_method_module(statements=100, methods=60)
    tree = ast.parse(source)
    methods = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_m_")
    ]
    assert len(methods) == 60
    ctx = FactoryBuildContext(filename="product_shape.py", catalog=default_catalog())
    t0 = time.perf_counter()
    for method in methods:
        build_node(
            method, filename="product_shape.py", role=SugarRole.DEFINITION, ctx=ctx
        )
    elapsed = time.perf_counter() - t0
    assert elapsed < 3.0, (
        f"factory of {60} product-shaped methods (multinomial/tomaxint Attribute "
        f"Calls) took {elapsed:.3f}s. Illegal residual: factory.select still "
        f"dominated by BuiltinCalleeUniverseSugar.owns import identity on "
        f"non-authenticated Attribute leaves. Replacement: leaf-gated coordinate "
        f"+ content-keyed source_symtable."
    )
