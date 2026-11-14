"""Inventory item 28 (#7757): an assert is reduced once, in context.

The universe rows, the ``facts`` row and the ``implications`` row of an assert
all read what it reduced to inside its owner's one reduction
(``tree_enumerate.owner_reduction``). None of them reduces the assert alone.
"""

from __future__ import annotations

from collections import Counter

_SOURCE = (
    "# item 28: an assert is reduced once\n"
    "def test_item_28_once(n):\n"
    "    x = n\n"
    "    x += 1\n"
    "    assert x == n + 1\n"
)


def _tree():
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree import nodes
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (_SOURCE, "test_item_28_once.py", blake3_512_of(_SOURCE.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, nodes.FunctionDef) and node.name == "test_item_28_once"
    )
    (source_assert,) = tuple(
        node for node in tree.nodes() if isinstance(node, nodes.Assert)
    )
    lc = source_assert.line_col_span()
    return tree, function, {"start_line": lc.start_line, "start_col": lc.start_col}


def test_every_reader_of_an_assert_reads_its_one_reduction(monkeypatch) -> None:
    from sugar_lift_py_tests import tree_enumerate
    from sugar_lift_py_tests.sugar.assert_sugar import AssertSugar

    tree, function, span = _tree()
    counts: Counter[int] = Counter()
    reduce_assert = AssertSugar.desugar

    def counted(self, ctx=None):
        counts[self.site.line_col_span.start_line] += 1
        return reduce_assert(self, ctx)

    monkeypatch.setattr(AssertSugar, "desugar", counted)
    monkeypatch.setattr(tree_enumerate, "_OWNER_REDUCTIONS", {})

    # The universe rows' reader, then the `facts` and `implications` readers.
    universe = tree_enumerate.owner_reduction(function).outcome
    fact_source, fact_outcome = tree_enumerate.assert_outcome(tree, span)
    implication_source, implication_outcome = tree_enumerate.assert_outcome(
        tree, span
    )
    tree_enumerate.fact_of(fact_outcome)

    assert universe is not None
    assert fact_source is not None and implication_source is not None
    assert fact_outcome is implication_outcome
    assert counts[span["start_line"]] == 1
