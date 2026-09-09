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


def test_reached_attribute_consumer_mints_the_countable_gap() -> None:
    # An Attribute whose exact span carries a deferred marker raises the
    # countable ImportValueUseResolutionGap when constructed (the force-floor
    # reaching it), rather than projecting an authenticated member.
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

    with pytest.raises(ImportValueUseResolutionGap):
        attr.sugar()


def test_unreached_attribute_without_marker_does_not_raise_the_gap() -> None:
    # The lying-twin control: the SAME attribute shape with NO deferred marker
    # must not mint the gap (the refusal is reachability + deferral scoped,
    # never fabricated).
    tree = _tree("def f(mod):\n    return mod.thing\n")
    attr = next(
        node
        for node in tree.root.walk()
        if isinstance(node, Attribute) and node.attr == "thing"
    )
    try:
        attr.sugar()
    except ImportValueUseResolutionGap:  # pragma: no cover
        pytest.fail("no deferred marker was seated; the gap must not appear")
    except Exception:
        pass  # an ordinary opaque-receiver refusal is fine; the GAP must not.
