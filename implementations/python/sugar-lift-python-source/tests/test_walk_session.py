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
    a = walk_session_for(tmp_path)
    b = walk_session_for(tmp_path / ".")
    assert a is b
    assert isinstance(a, SourceResolutionSession)


def test_walk_session_different_roots_are_isolated(tmp_path: Path) -> None:
    left = walk_session_for(tmp_path / "left")
    right = walk_session_for(tmp_path / "right")
    (tmp_path / "left").mkdir()
    (tmp_path / "right").mkdir()
    left2 = walk_session_for(tmp_path / "left")
    right2 = walk_session_for(tmp_path / "right")
    assert left2 is left
    assert right2 is right
    assert left is not right


def test_open_default_uses_walk_session(tmp_path: Path, monkeypatch) -> None:
    """Production open without resolution_session takes the walk owner for root."""
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_python_source import manager_summary_derivation as msd

    root = tmp_path / "ws"
    root.mkdir()
    path = root / "consumer.py"
    path.write_text("x = 1\n", encoding="utf-8")

    seen: list[object] = []
    original = msd.populate_source_derived_resource_refs

    def capture(source_file, *, root, path, session=None, **kwargs):
        seen.append(session)
        return original(source_file, root=root, path=path, session=session, **kwargs)

    monkeypatch.setattr(msd, "populate_source_derived_resource_refs", capture)

    open_source_file_for_construction(path, root=root)
    open_source_file_for_construction(path, root=root)
    assert len(seen) == 2
    assert seen[0] is seen[1] is walk_session_for(root), (
        "two opens under the same root must share the walk session so same-content "
        "re-open and census multi-file amortize projection memos"
    )


def test_open_explicit_session_bypasses_walk(tmp_path: Path, monkeypatch) -> None:
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_python_source import manager_summary_derivation as msd

    root = tmp_path / "ws"
    root.mkdir()
    path = root / "consumer.py"
    path.write_text("x = 1\n", encoding="utf-8")

    seen: list[object] = []
    original = msd.populate_source_derived_resource_refs

    def capture(source_file, *, root, path, session=None, **kwargs):
        seen.append(session)
        return original(source_file, root=root, path=path, session=session, **kwargs)

    monkeypatch.setattr(msd, "populate_source_derived_resource_refs", capture)

    isolated = SourceResolutionSession()
    open_source_file_for_construction(path, root=root, resolution_session=isolated)
    assert seen == [isolated]
    assert isolated is not walk_session_for(root)
