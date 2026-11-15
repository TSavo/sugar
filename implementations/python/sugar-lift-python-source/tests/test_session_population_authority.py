"""Population authority is constructed with a session, never inferred later."""

from pathlib import Path

import pytest

from sugar_lift_python_source.resolution_session import (
    SourceResolutionSession,
    clear_walk_sessions,
    session_or_new,
    walk_session_for,
)


def test_source_resolution_session_requires_an_explicit_roster() -> None:
    """Omitted and unknown rosters cannot construct the session state."""
    with pytest.raises(TypeError, match="enrolled_distributions"):
        SourceResolutionSession()  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="enrolled_distributions"):
        SourceResolutionSession(enrolled_distributions=None)  # type: ignore[arg-type]


def test_session_or_new_refuses_to_mint_unknown_authority() -> None:
    """The leaf helper may return authority, but cannot invent it."""
    with pytest.raises(TypeError, match="enrolled distribution roster"):
        session_or_new(None)

    constructed = session_or_new(
        None,
        enrolled_distributions=frozenset(),
    )
    assert constructed.enrolled_distributions == frozenset()

    empty = SourceResolutionSession(enrolled_distributions=frozenset())
    assert session_or_new(empty) is empty


def test_walk_session_requires_and_preserves_roster_authority(tmp_path: Path) -> None:
    """A walk cache key includes the roster whose projections it may serve."""
    clear_walk_sessions()
    try:
        with pytest.raises(TypeError, match="enrolled_distributions"):
            walk_session_for(tmp_path)  # type: ignore[call-arg]

        empty = walk_session_for(
            tmp_path,
            enrolled_distributions=frozenset(),
        )
        pandas = walk_session_for(
            tmp_path,
            enrolled_distributions=frozenset({"pandas"}),
        )
        assert empty.enrolled_distributions == frozenset()
        assert pandas.enrolled_distributions == frozenset({"pandas"})
        assert empty is not pandas
    finally:
        clear_walk_sessions()
