"""Reachability-scoped unresolved value-use deferral.

Manager receipt seating walks the whole frame span, but the manager's exit
contract only reaches the value-uses on its suppress/raise decision path.  An
unresolved value-use is therefore DEFERRED (a marker at the exact coordinate)
instead of eagerly voiding the manager; the value-use consumer mints the
identical countable ``ImportValueUseResolutionGap`` only if the force-floor
reaches the use.  These twins pin the marker table + the consumer refusal.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_source_tree.nodes import Attribute
from sugar_source_tree.panic import (
    BackendDefect,
    ImportValueUseResolutionGap,
    SugarNotWritten,
    UnresolvedImportValueUseV1,
)
from sugar_source_tree.tree import SourceFile


def _tree(src: str) -> SourceFile:
    return SourceFile(
        (src, "deferred_use.py", blake3_512_of(src.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _marker() -> UnresolvedImportValueUseV1:
    return UnresolvedImportValueUseV1(
        resolution_kind="target-outside-binding",
        target_symbol="python:_pytest.assertion.util._config.get_verbosity",
        dependency_module="_pytest.assertion.util",
    )


def test_defer_then_read_returns_the_marker() -> None:
    tree = _tree("x = 1\n")
    unit = tree.unit
    span = (1, 0, 1, 1)
    assert unit.deferred_unresolved_import_value_use(span) is None
    unit.defer_unresolved_import_value_use(
        span, _marker(), source_cid=unit.source_cid
    )
    assert unit.deferred_unresolved_import_value_use(span) == _marker()


def test_marker_as_gap_is_a_countable_terminal() -> None:
    gap = _marker().as_gap(blame="deferred_use.py:1:0")
    assert isinstance(gap, ImportValueUseResolutionGap)
    assert isinstance(gap, SugarNotWritten)
    assert "resolution-target-outside-binding" in str(gap)
    assert "get_verbosity" in str(gap)


def test_defer_refuses_a_non_marker_and_foreign_source_cid() -> None:
    unit = _tree("x = 1\n").unit
    with pytest.raises(BackendDefect):
        unit.defer_unresolved_import_value_use(
            (1, 0, 1, 1), object(), source_cid=unit.source_cid
        )
    with pytest.raises(BackendDefect):
        unit.defer_unresolved_import_value_use(
            (1, 0, 1, 1), _marker(), source_cid="blake3-512:deadbeef"
        )


def test_construct_over_a_deferred_marker_does_not_raise() -> None:
    # A deferred (proven message-only) value-use constructs its ordinary
    # AttributeSugar -- the opacity is resolved at reduce (a MessageOpaqueValue),
    # never a construct-time gap.  as_gap remains the SEAT-time abort path for a
    # decision-reaching unresolved value (see test_message_only_value_use.py).
    tree = _tree("def f(mod):\n    return mod.thing\n")
    unit = tree.unit
    attr = next(
        node
        for node in tree.root.walk()
        if isinstance(node, Attribute) and node.attr == "thing"
    )
    span = attr.line_col_span()
    key = (span.start_line, span.start_col, span.end_line, span.end_col)
    unit.defer_unresolved_import_value_use(key, _marker(), source_cid=unit.source_cid)

    # Must not raise ImportValueUseResolutionGap at construction.
    attr.sugar()


def test_marker_as_gap_still_available_for_seat_time_abort() -> None:
    # The decision-path abort path still mints the identical countable gap.
    gap = _marker().as_gap(blame="deferred_use.py:2:11")
    assert isinstance(gap, ImportValueUseResolutionGap)
