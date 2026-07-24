# SPDX-License-Identifier: MIT OR Apache-2.0
"""Bounded process-lifetime ownership for source_tables (census B1)."""

from __future__ import annotations

import ast

from sugar_lift_python_source import source_tables
from sugar_lift_python_source import source_tables_adapter
from sugar_lift_python_source.source_tables import (
    SOURCE_TABLE_CAPACITY,
    parsed_tree,
    source_lines,
    source_segment,
    source_splitlines,
)


def test_capacity_is_finite_and_positive() -> None:
    assert SOURCE_TABLE_CAPACITY > 0
    assert SOURCE_TABLE_CAPACITY == 64
    assert source_tables_adapter.SOURCE_TABLE_CAPACITY == SOURCE_TABLE_CAPACITY


def test_source_tables_are_lru_bounded_not_unbounded() -> None:
    """R axis: no maxsize=None on the process-lifetime tables."""
    for fn in (
        source_splitlines,
        source_lines,
    ):
        info = fn.cache_info()
        # lru_cache exposes maxsize; None would mean unbounded.
        assert info.maxsize is not None, f"{fn.__name__} must be bounded"
        assert info.maxsize == SOURCE_TABLE_CAPACITY
    # Dual residual parse lives on the adapter, still content-keyed LRU.
    assert source_tables_adapter._parsed.cache_info().maxsize == SOURCE_TABLE_CAPACITY


def test_tables_evict_past_capacity_without_losing_semantics() -> None:
    """Past capacity, recompute still returns correct results (eviction ok)."""
    # Clear so the test owns the cache population.
    source_splitlines.cache_clear()
    source_lines.cache_clear()
    source_tables_adapter._parsed.cache_clear()

    n = SOURCE_TABLE_CAPACITY + 8
    bodies = [f"x_{i} = {i}\n" for i in range(n)]
    for body in bodies:
        assert source_splitlines(body) == tuple(body.splitlines(keepends=True))
        assert source_lines(body) == tuple(ast._splitlines_no_ff(body))
        tree = parsed_tree(body)
        assert isinstance(tree, ast.Module)

    # Oldest entries may be gone; re-query still correct (recompute path).
    first = bodies[0]
    assert source_splitlines(first) == tuple(first.splitlines(keepends=True))
    assert source_lines(first) == tuple(ast._splitlines_no_ff(first))
    assert parsed_tree(first).body[0].targets[0].id == "x_0"  # type: ignore[attr-defined]

    # Cache never grows past capacity.
    assert source_splitlines.cache_info().currsize <= SOURCE_TABLE_CAPACITY
    assert source_lines.cache_info().currsize <= SOURCE_TABLE_CAPACITY
    assert source_tables_adapter._parsed.cache_info().currsize <= SOURCE_TABLE_CAPACITY


def test_source_segment_still_uses_line_table() -> None:
    source = "def f():\n    return 1\n"
    tree = parsed_tree(source)
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)
    segment = source_segment(source, fn)
    assert segment is not None
    assert "def f()" in segment


def test_source_lines_matches_parser_split_including_form_feed() -> None:
    """Form feed must NOT break a line — matches ast._splitlines_no_ff."""
    source = "a = 1\x0cb = 2\nc = 3\n"
    assert source_lines(source) == tuple(ast._splitlines_no_ff(source))
    # str.splitlines would split on form feed; our table must not.
    assert any("\x0c" in line for line in source_lines(source))


def test_public_source_tables_module_has_no_foreign_ast_import() -> None:
    """Construction currency: line tables never import stdlib ast."""
    text = (
        __import__("pathlib").Path(source_tables.__file__).read_text(encoding="utf-8")
    )
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(
                alias.name == "ast" or alias.name.startswith("ast.")
                for alias in node.names
            )
        if isinstance(node, ast.ImportFrom):
            assert not (node.module and node.module.split(".", 1)[0] == "ast")


def test_dead_dual_path_tables_are_gone() -> None:
    """Parent / locus / symtable caches had no production callers — deleted."""
    for name in (
        "parsed_parents",
        "parsed_locus_index",
        "locate_parsed_node",
        "source_symtable",
    ):
        assert not hasattr(source_tables, name), name
