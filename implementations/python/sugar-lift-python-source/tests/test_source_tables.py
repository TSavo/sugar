# SPDX-License-Identifier: MIT OR Apache-2.0
"""Bounded process-lifetime ownership for source_tables (census B1)."""

from __future__ import annotations

import ast

from sugar_lift_python_source import source_tables
from sugar_lift_python_source.source_tables import (
    SOURCE_TABLE_CAPACITY,
    parsed_parents,
    parsed_tree,
    source_lines,
    source_segment,
    source_splitlines,
)


def test_capacity_is_finite_and_positive() -> None:
    assert SOURCE_TABLE_CAPACITY > 0
    assert SOURCE_TABLE_CAPACITY == 64


def test_source_tables_are_lru_bounded_not_unbounded() -> None:
    """R axis: no maxsize=None on the four process-lifetime tables."""
    for fn in (source_splitlines, source_lines, parsed_parents):
        info = fn.cache_info()
        # lru_cache exposes maxsize; None would mean unbounded.
        assert info.maxsize is not None, f"{fn.__name__} must be bounded"
        assert info.maxsize == SOURCE_TABLE_CAPACITY
    # _parsed is wrapped only via parsed_tree; check the private table.
    assert source_tables._parsed.cache_info().maxsize == SOURCE_TABLE_CAPACITY


def test_tables_evict_past_capacity_without_losing_semantics() -> None:
    """Past capacity, recompute still returns correct results (eviction ok)."""
    # Clear so the test owns the cache population.
    source_splitlines.cache_clear()
    source_lines.cache_clear()
    source_tables._parsed.cache_clear()
    parsed_parents.cache_clear()

    n = SOURCE_TABLE_CAPACITY + 8
    bodies = [f"x_{i} = {i}\n" for i in range(n)]
    for body in bodies:
        assert source_splitlines(body) == tuple(body.splitlines(keepends=True))
        assert source_lines(body) == tuple(ast._splitlines_no_ff(body))
        tree = parsed_tree(body)
        assert isinstance(tree, ast.Module)
        parents = parsed_parents(body)
        assert parents is not None
        assert isinstance(parents[0], ast.Module)

    # Oldest entries may be gone; re-query still correct (recompute path).
    first = bodies[0]
    assert source_splitlines(first) == tuple(first.splitlines(keepends=True))
    assert source_lines(first) == tuple(ast._splitlines_no_ff(first))
    assert parsed_tree(first).body[0].targets[0].id == "x_0"  # type: ignore[attr-defined]

    # Cache never grows past capacity.
    assert source_splitlines.cache_info().currsize <= SOURCE_TABLE_CAPACITY
    assert source_lines.cache_info().currsize <= SOURCE_TABLE_CAPACITY
    assert source_tables._parsed.cache_info().currsize <= SOURCE_TABLE_CAPACITY
    assert parsed_parents.cache_info().currsize <= SOURCE_TABLE_CAPACITY


def test_source_segment_still_uses_line_table() -> None:
    source = "def f():\n    return 1\n"
    tree = parsed_tree(source)
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)
    segment = source_segment(source, fn)
    assert segment is not None
    assert "def f()" in segment
