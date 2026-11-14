"""The unanswered-call collector and its rows (PR B on #7766, step 8).

``UnknownCalleeCallV1.faces`` records a call only while a collector is open,
and only the universe full scan mint packages (and the link-unit reduction a
resumed function gets) opens one. Every reduction elsewhere, the preliminary
fold and every seek included, records nothing.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests import tree_enumerate as _tree
from sugar_lift_py_tests import unanswered_calls
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1

_SRC = "blake3-512:" + "ab" * 64


class _Site:
    """A fragment's two coordinates: its unit's source CID and its span."""

    class _Span:
        start_line, start_col, end_line, end_col = 5, 11, 5, 19

    source_cid = _SRC
    line_col_span = _Span()


def test_no_collector_records_nothing() -> None:
    unanswered_calls.record("python:idn.ident", _Site())  # no error, no effect
    with unanswered_calls.collecting() as calls:
        pass
    assert calls == []


def test_a_collector_records_symbol_and_coordinate() -> None:
    with unanswered_calls.collecting() as calls:
        unanswered_calls.record("python:idn.ident", _Site())
        unanswered_calls.record(None, _Site())
    coordinate = SourceFragmentCoordinateV1(_SRC, 5, 11, 5, 19)
    assert calls == [("python:idn.ident", coordinate), (None, coordinate)]


def test_a_call_without_a_site_is_loud_while_collecting() -> None:
    with unanswered_calls.collecting():
        with pytest.raises(ValueError, match="no site"):
            unanswered_calls.record(None, None)


def test_one_row_per_distinct_symbol_and_site() -> None:
    coordinate = SourceFragmentCoordinateV1(_SRC, 5, 11, 5, 19)
    other = SourceFragmentCoordinateV1(_SRC, 6, 4, 6, 9)
    calls = [
        ("python:idn.ident", coordinate),
        ("python:idn.ident", coordinate),  # the same call reduced twice
        (None, other),
    ]
    rows = [
        row.to_rpc_with_term_table(None)
        for row in _tree.unanswered_call_rows(calls, "m.py")
    ]
    assert rows == [
        {
            "kind": "undecided",
            "symbol": "python:idn.ident",
            "site": {"file": "m.py", **coordinate.wire()},
            "reason": {"unanswered": {}},
        },
        {
            "kind": "undecided",
            "symbol": None,
            "site": {"file": "m.py", **other.wire()},
            "reason": {"unanswered": {}},
        },
    ]
