"""A refused top-level manager construction is reduced once per session.

A file's with-sites are populated twice under one walk session (the enumerate
pass and the audit roll call).  ``construct_manager_behavior`` remembers a
refusal (a returned ``ManagerConstructionGapV1`` or a raised
``SugarNotWritten``) under every input it reads, so the second populate reads
the same verdict.  A constructed behavior is never remembered, a different
actual is a different construction, and a construction entered while another
projection is in flight is never remembered.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_python_source import manager_construction as mc
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.panic import SugarNotWritten


def _actual(cid: str):
    return SimpleNamespace(testimony=SimpleNamespace(cid=cid))


_RESOLVED = SimpleNamespace(cid="resolved-cid")
_GRAPH = SimpleNamespace(distribution_artifact_cid="artifact-cid")


def _construct(session, *, actual="a1", calls):
    return mc.construct_manager_behavior(
        _RESOLVED,
        graph=_GRAPH,
        actuals=(_actual(actual),),
        session=session,
    )


@pytest.fixture
def counted(monkeypatch):
    calls: list = []
    verdict: dict = {}

    def once(resolved, **kwargs):
        calls.append(kwargs["actuals"][0].testimony.cid)
        outcome = verdict["next"]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(mc, "_construct_manager_behavior_once", once)
    return calls, verdict


def _session():
    return SourceResolutionSession(enrolled_distributions=frozenset())


def test_a_returned_gap_is_served_to_the_second_populate(counted):
    calls, verdict = counted
    gap = mc.ManagerConstructionGapV1("force-floor", "resolved-cid", "x")
    verdict["next"] = gap
    session = _session()

    assert _construct(session, calls=calls) is gap
    assert _construct(session, calls=calls) is gap
    assert calls == ["a1"]


def test_a_raised_refusal_is_raised_again_without_reducing(counted):
    calls, verdict = counted
    refusal = SugarNotWritten(
        owner="test", blame="site", observed="o", requested="r", fix="f"
    )
    verdict["next"] = refusal
    session = _session()

    for _ in range(2):
        with pytest.raises(SugarNotWritten) as raised:
            _construct(session, calls=calls)
        assert raised.value is refusal
    assert calls == ["a1"]


def test_a_constructed_behavior_is_never_remembered(counted):
    # Lying twin: a success served from the memo would hand the second open
    # nodes of the first; it is reduced again.
    calls, verdict = counted
    verdict["next"] = object()
    session = _session()

    _construct(session, calls=calls)
    _construct(session, calls=calls)
    assert calls == ["a1", "a1"]


def test_a_different_actual_is_a_different_construction(counted):
    calls, verdict = counted
    verdict["next"] = mc.ManagerConstructionGapV1("force-floor", "resolved-cid", "x")
    session = _session()

    _construct(session, actual="a1", calls=calls)
    _construct(session, actual="a2", calls=calls)
    assert calls == ["a1", "a2"]


def test_a_construction_inside_an_active_projection_is_not_remembered(counted):
    calls, verdict = counted
    verdict["next"] = mc.ManagerConstructionGapV1("cycle", "resolved-cid", "x")
    session = _session()
    session.frame_active.add(("in-flight",))

    _construct(session, calls=calls)
    _construct(session, calls=calls)
    assert calls == ["a1", "a1"]


def test_a_disabled_session_never_remembers(counted):
    calls, verdict = counted
    verdict["next"] = mc.ManagerConstructionGapV1("force-floor", "resolved-cid", "x")
    session = SourceResolutionSession(
        enrolled_distributions=frozenset(), enabled=False
    )

    _construct(session, calls=calls)
    _construct(session, calls=calls)
    assert calls == ["a1", "a1"]
