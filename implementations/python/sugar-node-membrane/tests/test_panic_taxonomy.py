"""Two panics, two circumstances: MembraneMissing vs MembraneProviderDefect.

Before this split, a single ``MembranePanic`` conflated "our vocabulary is
incomplete" with "the provider/adapter is buggy," resolved only by a caller
reading the ``owner`` string. These tests pin the split: each concrete class
fires in its own circumstance, and — the load-bearing assertion — catching
one does NOT catch the other. Both still subclass the common ``MembranePanic``
base, for callers (like ``corpus.py``) that genuinely need "any membrane
panic happened."
"""

from __future__ import annotations

import pytest

from sugar_node_membrane.nodes import resolve_kind
from sugar_node_membrane.operators import operator_for
from sugar_node_membrane.panic import (
    MembraneMissing,
    MembranePanic,
    MembraneProviderDefect,
)
from sugar_node_membrane.spans import LineTable, Span


def test_both_are_membrane_panic_but_distinct_from_each_other():
    assert issubclass(MembraneMissing, MembranePanic)
    assert issubclass(MembraneProviderDefect, MembranePanic)
    assert not issubclass(MembraneMissing, MembraneProviderDefect)
    assert not issubclass(MembraneProviderDefect, MembraneMissing)


def test_unknown_backend_kind_is_a_missing_not_a_provider_defect():
    """resolve_kind: a shape the provider legitimately produced, but our
    vocabulary has no membrane class for it — the MISSING case."""
    with pytest.raises(MembraneMissing):
        resolve_kind("NoSuchKind", observed_at="test")


def test_unknown_operator_kind_is_a_missing_not_a_provider_defect():
    with pytest.raises(MembraneMissing):
        operator_for("NoSuchOperator")


def test_degenerate_span_is_a_provider_defect_not_a_missing():
    """spans.Span: a structurally invalid position (end before start) —
    always the adapter/provider's own defect, never a vocabulary gap."""
    with pytest.raises(MembraneProviderDefect):
        Span(5, 2)


def test_out_of_range_line_is_a_provider_defect_not_a_missing():
    table = LineTable("x = 1\n")
    with pytest.raises(MembraneProviderDefect):
        table.offset(99, 0)


def test_catching_missing_does_not_catch_provider_defect():
    with pytest.raises(MembraneProviderDefect):
        try:
            Span(5, 2)
        except MembraneMissing:
            pytest.fail("MembraneMissing must not catch a provider defect")


def test_catching_provider_defect_does_not_catch_missing():
    with pytest.raises(MembraneMissing):
        try:
            resolve_kind("NoSuchKind", observed_at="test")
        except MembraneProviderDefect:
            pytest.fail("MembraneProviderDefect must not catch a missing")


def test_catching_the_common_base_catches_both():
    """The base exists for callers (corpus.py) that need 'any membrane
    panic happened' — never as the easy default that re-conflates them."""
    with pytest.raises(MembranePanic):
        resolve_kind("NoSuchKind", observed_at="test")
    with pytest.raises(MembranePanic):
        Span(5, 2)
