"""Session owns dependency top-level graphs — ask auth once per top.

Cold test_pandas open called authenticate_dependency_top_level 65× across
only 5 unique tops (warnings/re/inspect ×21 each). Process cache made each
hit cheap; session ownership makes the ask once per construction session
(and walk-scoped sessions share the map across multi-file open).
"""

from __future__ import annotations

from sugar_lift_python_source.manager_construction import (
    _bind_dependency_graphs,
    _dependency_graph_for_top,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession


def test_dependency_graph_for_top_asks_auth_once(monkeypatch) -> None:
    # Cache-only unit test: no distribution graph is enrolled.
    session = SourceResolutionSession(enrolled_distributions=frozenset())
    local: dict = {}
    calls: list[str] = []

    class _FakeGraph:
        def __init__(self, name: str) -> None:
            self.distribution_name = name

    def fake_auth(top_level, distribution_index=None):  # type: ignore[no-untyped-def]
        calls.append(top_level)
        return _FakeGraph(top_level)

    monkeypatch.setattr(
        "sugar_lift_python_source.dependency_artifact.authenticate_dependency_top_level",
        fake_auth,
    )

    g1 = _dependency_graph_for_top("warnings", session=session, dependency_graphs=local)
    g2 = _dependency_graph_for_top("warnings", session=session, dependency_graphs=local)
    # Fresh local map still hits session (ask once per content, not path).
    g3 = _dependency_graph_for_top("warnings", session=session, dependency_graphs={})
    assert g1 is g2 is g3
    assert calls == ["warnings"]
    assert session.dependency_graphs["warnings"] is g1


def test_bind_dependency_graphs_seeds_from_session() -> None:
    session = SourceResolutionSession(enrolled_distributions=frozenset())
    session.dependency_graphs["re"] = object()
    bound = _bind_dependency_graphs(session, {})
    assert bound["re"] is session.dependency_graphs["re"]
    # None binds the session map itself (write-through).
    direct = _bind_dependency_graphs(session, None)
    assert direct is session.dependency_graphs


def test_five_unique_tops_auth_once_each(monkeypatch) -> None:
    """Black cold profile shape: 5 tops, path-local re-ask → 1 auth each."""
    session = SourceResolutionSession(enrolled_distributions=frozenset())
    calls: list[str] = []

    class _FakeGraph:
        def __init__(self, name: str) -> None:
            self.distribution_name = name

    def fake_auth(top_level, distribution_index=None):  # type: ignore[no-untyped-def]
        calls.append(top_level)
        return _FakeGraph(top_level)

    monkeypatch.setattr(
        "sugar_lift_python_source.dependency_artifact.authenticate_dependency_top_level",
        fake_auth,
    )

    tops = ("warnings", "re", "inspect", "sys", "os")
    # Simulate 21 path-local maps (as on one test_pandas open).
    for _ in range(21):
        local: dict = {}
        for top in tops:
            _dependency_graph_for_top(top, session=session, dependency_graphs=local)

    assert calls == list(tops)
    assert set(session.dependency_graphs) == set(tops)
