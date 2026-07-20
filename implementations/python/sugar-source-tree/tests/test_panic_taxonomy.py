"""Two panics, two circumstances: VocabularyMissing vs BackendDefect.

Before this split, a single ``SourceTreePanic`` conflated "our vocabulary is
incomplete" with "the backend/adapter is buggy," resolved only by a caller
reading the ``owner`` string. These tests pin the split: each concrete class
fires in its own circumstance, and — the load-bearing assertion — catching
one does NOT catch the other. Both still subclass the common ``SourceTreePanic``
base, for callers (like ``corpus.py``) that genuinely need "any tree
panic happened."
"""

from __future__ import annotations

import pytest

from sugar_source_tree.nodes import resolve_kind
from sugar_source_tree.operators import operator_for
from sugar_source_tree.panic import (
    VocabularyMissing,
    SourceTreePanic,
    BackendDefect,
)
from sugar_source_tree.spans import LineTable, Span


def test_both_are_membrane_panic_but_distinct_from_each_other():
    assert issubclass(VocabularyMissing, SourceTreePanic)
    assert issubclass(BackendDefect, SourceTreePanic)
    assert not issubclass(VocabularyMissing, BackendDefect)
    assert not issubclass(BackendDefect, VocabularyMissing)


def test_unknown_backend_kind_is_a_missing_not_a_provider_defect():
    """resolve_kind: a shape the backend legitimately produced, but our
    vocabulary has no node class for it — the MISSING case."""
    with pytest.raises(VocabularyMissing):
        resolve_kind("NoSuchKind", observed_at="test")


def test_unknown_operator_kind_is_a_missing_not_a_provider_defect():
    with pytest.raises(VocabularyMissing):
        operator_for("NoSuchOperator")


def test_degenerate_span_is_a_provider_defect_not_a_missing():
    """spans.Span: a structurally invalid position (end before start) —
    always the adapter/backend's own defect, never a vocabulary gap."""
    with pytest.raises(BackendDefect):
        Span(5, 2)


def test_out_of_range_line_is_a_provider_defect_not_a_missing():
    table = LineTable("x = 1\n")
    with pytest.raises(BackendDefect):
        table.offset(99, 0)


def test_catching_missing_does_not_catch_provider_defect():
    with pytest.raises(BackendDefect):
        try:
            Span(5, 2)
        except VocabularyMissing:
            pytest.fail("VocabularyMissing must not catch a backend defect")


def test_catching_provider_defect_does_not_catch_missing():
    with pytest.raises(VocabularyMissing):
        try:
            resolve_kind("NoSuchKind", observed_at="test")
        except BackendDefect:
            pytest.fail("BackendDefect must not catch a missing")


def test_catching_the_common_base_catches_both():
    """The base exists for callers (corpus.py) that need 'any tree
    panic happened' — never as the easy default that re-conflates them."""
    with pytest.raises(SourceTreePanic):
        resolve_kind("NoSuchKind", observed_at="test")
    with pytest.raises(SourceTreePanic):
        Span(5, 2)
