"""Walk-scoped SourceResolutionSession — multi-resolve owner for one workspace.

Orange measured cross-file shared session ~15% (frame_results after 20 files = 1).
This tooth pins the authority owner and same-content re-open amortization under
one root — not a 6× claim.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_python_source.resolution_session import (
    SourceResolutionSession,
    clear_walk_sessions,
    walk_session_for,
)


def setup_function() -> None:
    clear_walk_sessions()


def teardown_function() -> None:
    clear_walk_sessions()


def test_walk_session_same_root_is_one_session(tmp_path: Path) -> None:
    a = walk_session_for(tmp_path, enrolled_distributions=frozenset())
    b = walk_session_for(tmp_path / ".", enrolled_distributions=frozenset())
    assert a is b
    assert isinstance(a, SourceResolutionSession)


def test_walk_session_different_roots_are_isolated(tmp_path: Path) -> None:
    left = walk_session_for(tmp_path / "left", enrolled_distributions=frozenset())
    right = walk_session_for(tmp_path / "right", enrolled_distributions=frozenset())
    (tmp_path / "left").mkdir()
    (tmp_path / "right").mkdir()
    left2 = walk_session_for(tmp_path / "left", enrolled_distributions=frozenset())
    right2 = walk_session_for(tmp_path / "right", enrolled_distributions=frozenset())
    assert left2 is left
    assert right2 is right
    assert left is not right
