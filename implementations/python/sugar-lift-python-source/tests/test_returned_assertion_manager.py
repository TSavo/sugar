"""Authenticated returned-manager classification in the pinned pandas corpus.

The truthful face intentionally stays red until ordinary returned-manager
classification reaches the helper's authenticated manager.  On #6501 it stops
at ``binary_operation_exception_floor:SymbolicValue + CallSiteValue``.  Moving
past that point with receiver construction and nested ``__call__`` following is
a separate general mechanism, not permission for a helper-name shortcut here.
"""

from __future__ import annotations

from functools import cache

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import (
    SourceDerivedContextManagerRefV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction


@cache
def _feather_tree():
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.file_count) == ("3.0.3", 1421)
    path = corpus.root / "tests/io/test_feather.py"
    return open_source_file_for_construction(
        path,
        root=corpus.root.parent,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=True,
    )


def _with_at(line: int):
    return next(
        node
        for node in _feather_tree().nodes()
        if node.kind == "With" and node.line_col_span().start_line == line
    )


def test_external_error_raised_follows_authenticated_returned_manager() -> None:
    """Truthful: local import plus returned manager supplies the classification."""
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        OptionalFormalArgumentProjectionV1,
    )
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )

    with_node = _with_at(40)
    reference = with_node._prebound_manager_resolution(with_node.items[0])

    assert isinstance(reference, SourceDerivedContextManagerRefV1), reference
    assert isinstance(reference.semantics, EffectBoundarySemanticsV1)
    # ``match=None`` is written and therefore remains the optional formal
    # projection; call construction must deliver the native NoneValue actual.
    # Treating it as an absent NoMessagePatternV1 would erase that distinction.
    assert isinstance(
        reference.semantics.message_pattern_operand,
        OptionalFormalArgumentProjectionV1,
    )
    assert isinstance(with_node.sugar(), WithEffectBoundarySugar)


def test_adjacent_computed_class_raises_stays_typed_opaque() -> None:
    """Lying twin: an unfollowable computed class cannot borrow sibling proof."""
    from sugar_source_tree.panic import WithConstructionGap, WithConstructionGapKind

    with_node = _with_at(33)
    with pytest.raises(WithConstructionGap) as caught:
        with_node.sugar()

    assert caught.value.coordinate.start_line == 33
    assert caught.value.gap_kind is WithConstructionGapKind.FORCE_FLOOR
    assert "binary_operation_exception_floor" in caught.value.observed
