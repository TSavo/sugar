"""frame_holds lifetime tracks frame_results — LRU co-eviction.

Walk-scoped sessions that retained every hold for the whole corpus recreated
shared-context accumulation. Tooth: hold is released when its memo row is
evicted; hit refreshes order; limit is respected.
"""

from __future__ import annotations

import os

from sugar_lift_python_source.resolution_session import (
    SourceResolutionSession,
    _frame_memo_limit,
)


def test_frame_memo_limit_default() -> None:
    prev = os.environ.pop("SUGAR_SESSION_FRAME_MEMO_LIMIT", None)
    try:
        assert _frame_memo_limit() == 512
        os.environ["SUGAR_SESSION_FRAME_MEMO_LIMIT"] = "3"
        assert _frame_memo_limit() == 3
        os.environ["SUGAR_SESSION_FRAME_MEMO_LIMIT"] = "0"
        assert _frame_memo_limit() == 1  # floor
    finally:
        if prev is None:
            os.environ.pop("SUGAR_SESSION_FRAME_MEMO_LIMIT", None)
        else:
            os.environ["SUGAR_SESSION_FRAME_MEMO_LIMIT"] = prev


def test_frame_holds_evict_with_memo_row(monkeypatch) -> None:
    """Hold must not outlive the memo it guards."""
    monkeypatch.setenv("SUGAR_SESSION_FRAME_MEMO_LIMIT", "2")
    # Memo-storage unit test: no distribution graph is enrolled.
    session = SourceResolutionSession(enrolled_distributions=frozenset())

    holds = [object() for _ in range(4)]
    for i, hold in enumerate(holds):
        session.remember_frame(("def", i), result=f"frame-{i}", hold=hold)

    assert len(session.frame_results) == 2
    assert len(session.frame_holds) == 2
    # Oldest two keys (0, 1) dropped; 2 and 3 remain.
    assert ("def", 0) not in session.frame_results
    assert ("def", 0) not in session.frame_holds
    assert ("def", 1) not in session.frame_results
    assert ("def", 1) not in session.frame_holds
    assert session.frame_results[("def", 2)] == "frame-2"
    assert session.frame_holds[("def", 2)] is holds[2]
    assert session.frame_results[("def", 3)] == "frame-3"
    assert session.frame_holds[("def", 3)] is holds[3]


def test_frame_hit_refreshes_lru_order(monkeypatch) -> None:
    """A hit keeps its hold; next eviction drops a colder key."""
    monkeypatch.setenv("SUGAR_SESSION_FRAME_MEMO_LIMIT", "2")
    session = SourceResolutionSession(enrolled_distributions=frozenset())
    h0, h1, h2 = object(), object(), object()
    session.remember_frame(("k", 0), "r0", hold=h0)
    session.remember_frame(("k", 1), "r1", hold=h1)
    # Touch key 0 so key 1 is oldest.
    assert session.frame_hit(("k", 0)) == "r0"
    session.remember_frame(("k", 2), "r2", hold=h2)

    assert ("k", 1) not in session.frame_results
    assert ("k", 1) not in session.frame_holds
    assert session.frame_holds[("k", 0)] is h0
    assert session.frame_holds[("k", 2)] is h2
    assert set(session.frame_results) == {("k", 0), ("k", 2)}


def test_remember_frame_without_hold_still_bounded(monkeypatch) -> None:
    """Gap memos (no hold) also count toward the limit."""
    monkeypatch.setenv("SUGAR_SESSION_FRAME_MEMO_LIMIT", "2")
    session = SourceResolutionSession(enrolled_distributions=frozenset())
    session.remember_frame(("g", 0), "gap0")
    session.remember_frame(("g", 1), "gap1", hold=object())
    session.remember_frame(("g", 2), "gap2")
    assert len(session.frame_results) == 2
    assert ("g", 0) not in session.frame_results
    assert ("g", 1) in session.frame_results
    assert ("g", 2) in session.frame_results
