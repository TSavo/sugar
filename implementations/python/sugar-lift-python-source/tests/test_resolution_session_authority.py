"""Authority twins for the source-resolution memo.

A memo that can change an answer is not a memo. These eight twins pin that
``SourceResolutionSession`` bounds every resolution memo, and each carries a
discrimination arm that bites: it perturbs the input and shows the answer
actually moves, so the positive assertion cannot pass vacuously.

The last twin is the load-bearing law: disabling the memo entirely must change
performance ONLY -- never a formula, never a gap, never a verdict.
"""

from __future__ import annotations

import csv
import importlib.metadata
import sys
from pathlib import Path

import pytest

from sugar_lift_python_source import manager_construction as mc
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import (
    resolve_source_visible_frame,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession

_PACKAGE = "from example_pkg.implementation import build\n"
_IMPL_A = "def build(value):\n    return value\n"
_IMPL_B = "def build(value):\n    return value + 1\n"


def _install(root: Path, *, implementation_source: str):
    """Install one authenticated distribution seat under ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    package = root / "example_pkg"
    package.mkdir()
    (package / "__init__.py").write_text(_PACKAGE, encoding="utf-8")
    (package / "implementation.py").write_text(implementation_source, encoding="utf-8")
    metadata = root / "example_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: example-dist\nVersion: 1.0\n", encoding="utf-8"
    )
    (metadata / "top_level.txt").write_text("example_pkg\n", encoding="utf-8")
    recorded = (
        "example_pkg/__init__.py",
        "example_pkg/implementation.py",
        "example_dist-1.0.dist-info/METADATA",
        "example_dist-1.0.dist-info/top_level.txt",
        "example_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for path in recorded:
            writer.writerow((path, "", ""))
    sys.modules.pop("example_pkg", None)
    sys.modules.pop("example_pkg.implementation", None)
    return importlib.metadata.Distribution.at(metadata)


def _receipt(root: Path):
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts

    source = "import example_pkg\nexample_pkg.build(1)\n"
    path = root / "consumer.py"
    path.write_text(source, encoding="utf-8")
    receipts, _ = authenticated_import_use_receipts(
        root, path, source, blake3_512_of(source.encode("utf-8")), module_identities={}
    )
    assert len(receipts) == 1
    return receipts[0]


def _project(tmp_path: Path, name: str, implementation_source: str):
    """One independent project: its own seat, graph, and consumer receipt."""
    root = tmp_path / name
    distribution = _install(root, implementation_source=implementation_source)
    graph = DependencyArtifactGraph.authenticate(distribution)
    return graph, _receipt(root)


def _resolve(project, session):
    graph, receipt = project
    resolved = resolve_import_binding(receipt, graph=graph, session=session)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    return resolved


def _verdict(project, session):
    """The full observable answer: resolution identity + projected frame."""
    graph, _ = project
    resolved = _resolve(project, session)
    projected = resolve_source_visible_frame(resolved, graph=graph, session=session)
    assert isinstance(projected, tuple), projected
    frame, target = projected
    return {
        "resolved_cid": resolved.cid,
        "module_name": resolved.module_name,
        "source_cid": resolved.source_cid,
        "fragment_cid": resolved.definition.fragment_cid,
        "frame_cid": frame.frame_cid,
        "target_name": target.name,
    }


class _MaterializeCounter:
    """Count SourceFile materializations inside ``resolve_source_visible_frame``."""

    def __init__(self) -> None:
        self.count = 0

    def __enter__(self):
        from sugar_source_tree.tree import SourceFile

        self._original = SourceFile
        counter = self

        class CountingSourceFile(SourceFile):
            def __init__(self, *args, **kwargs):
                counter.count += 1
                super().__init__(*args, **kwargs)

        mc.SourceFile = CountingSourceFile  # type: ignore[misc, assignment]
        return self

    def __exit__(self, *exc):
        mc.SourceFile = self._original  # type: ignore[misc, assignment]
        return False


# ---------------------------------------------------------------- twin 1


def test_cold_result_equals_warm_result(tmp_path: Path) -> None:
    """A warm memo answers exactly what a cold resolution answers."""
    project = _project(tmp_path, "p", _IMPL_A)

    cold = _verdict(project, SourceResolutionSession())
    session = SourceResolutionSession()
    _verdict(project, session)  # warm it
    warm = _verdict(project, session)

    assert cold == warm

    # Discrimination: the memo is genuinely consulted, so equality above is not
    # vacuous -- a warm session re-answers without re-materializing.
    assert session.export_resolutions and session.frame_results
    with _MaterializeCounter() as counter:
        _verdict(project, session)
    assert counter.count == 0, "warm session still re-materialized: memo is dead"
    with _MaterializeCounter() as cold_counter:
        _verdict(project, SourceResolutionSession())
    assert cold_counter.count >= 1, "cold session did no work: twin cannot bite"


# ---------------------------------------------------------------- twin 2


def test_a_then_b_equals_b_then_a(tmp_path: Path) -> None:
    """Resolution order inside one session cannot change either answer."""
    a = _project(tmp_path, "a", _IMPL_A)
    b = _project(tmp_path, "b", _IMPL_B)

    forward = SourceResolutionSession()
    a_first = _verdict(a, forward)
    b_second = _verdict(b, forward)

    backward = SourceResolutionSession()
    b_first = _verdict(b, backward)
    a_second = _verdict(a, backward)

    assert a_first == a_second
    assert b_first == b_second

    # Discrimination: A and B really do answer differently, so an order that
    # leaked one into the other would have been caught above.
    assert a_first["fragment_cid"] != b_first["fragment_cid"]


# ---------------------------------------------------------------- twin 3


def test_isolated_result_equals_result_after_other_work(tmp_path: Path) -> None:
    """A project's answer is the same alone as it is after a full population."""
    target = _project(tmp_path, "target", _IMPL_A)
    noise = _project(tmp_path, "noise", _IMPL_B)

    isolated = _verdict(target, SourceResolutionSession())

    crowded_session = SourceResolutionSession()
    _verdict(noise, crowded_session)
    crowded = _verdict(target, crowded_session)

    assert isolated == crowded

    # Discrimination: the noise really ran and really populated the session, so
    # "crowded" is not secretly the isolated path.
    assert len(crowded_session.frame_results) >= 2


# ---------------------------------------------------------------- twin 4


def test_changed_source_content_invalidates_the_answer(tmp_path: Path) -> None:
    """Different source content must never be served the earlier answer."""
    session = SourceResolutionSession()
    before = _verdict(_project(tmp_path, "v1", _IMPL_A), session)
    after = _verdict(_project(tmp_path, "v2", _IMPL_B), session)

    # Discrimination arm and assertion are the same edge: the memo did not
    # answer for content it never saw.
    assert before["source_cid"] != after["source_cid"], "sourceStamp did not move"
    assert before["fragment_cid"] != after["fragment_cid"]
    assert before["frame_cid"] != after["frame_cid"]

    # ...and the unchanged half still agrees, so the difference is content, not
    # session churn.
    assert before["module_name"] == after["module_name"]
    assert before["target_name"] == after["target_name"]


# ---------------------------------------------------------------- twin 5


def test_equal_paths_under_different_authorities_do_not_alias(tmp_path: Path) -> None:
    """Same module path + same exported name, different authority, no alias."""
    session = SourceResolutionSession()
    left_graph, _ = left = _project(tmp_path, "left", _IMPL_A)
    right_graph, _ = right = _project(tmp_path, "right", _IMPL_B)

    left_answer = _verdict(left, session)
    right_answer = _verdict(right, session)

    # Everything a path-or-name key would see is identical...
    assert left_answer["module_name"] == right_answer["module_name"]
    assert left_answer["target_name"] == right_answer["target_name"]
    # ...and the authority is the only thing separating them.
    assert left_graph.distribution_artifact_cid != right_graph.distribution_artifact_cid
    assert left_answer["fragment_cid"] != right_answer["fragment_cid"]

    # Discrimination: drop the authority from the key and the two collapse to
    # one entry -- which is exactly the aliasing this twin forbids.
    keys = list(session.export_resolutions)
    assert len({key[0] for key in keys}) == 2, keys
    assert len({key[1:] for key in keys}) == 1, keys


# ---------------------------------------------------------------- twin 6


def test_distinct_sessions_do_not_share_a_control_context(tmp_path: Path) -> None:
    """No construction ever reads another construction's live context.

    The projected ``target`` Node is bound to a ``TreeConstructionContextV1``
    that the projection WRITES into (``source_class_bases``,
    ``source_call_frames``). Two sessions must therefore never be handed the
    same node object.
    """
    graph, receipt = project = _project(tmp_path, "p", _IMPL_A)

    def project_target(session):
        resolved = _resolve(project, session)
        _frame, target = resolve_source_visible_frame(
            resolved, graph=graph, session=session
        )
        return target

    first = project_target(SourceResolutionSession())
    second = project_target(SourceResolutionSession())

    assert first is not second
    assert first.unit.construction_context is not second.unit.construction_context

    # Discrimination: inside ONE session the node IS shared -- that is the
    # amortization this repair preserves, and it proves the check above is
    # detecting session identity rather than always-fresh construction.
    shared = SourceResolutionSession()
    assert project_target(shared) is project_target(shared)


# ---------------------------------------------------------------- twin 7


def test_one_project_cannot_warm_another_projects_result(tmp_path: Path) -> None:
    """A warm session for project A does no work on behalf of project B."""
    a = _project(tmp_path, "a", _IMPL_A)
    b = _project(tmp_path, "b", _IMPL_A)  # byte-identical module source

    session_a = SourceResolutionSession()
    _verdict(a, session_a)

    session_b = SourceResolutionSession()
    with _MaterializeCounter() as counter:
        _verdict(b, session_b)
    assert counter.count >= 1, "project B was served project A's materialization"

    # The memo KEYS may coincide -- byte-identical content addresses to the same
    # CID, and that is what content addressing means.  What must never coincide
    # is the VALUE: a projected node carries a live construction context, and
    # project B must own its own.
    ((a_frame, a_target),) = session_a.frame_results.values()
    ((b_frame, b_target),) = session_b.frame_results.values()
    assert a_target is not b_target
    assert a_frame is not b_frame
    assert a_target.unit.construction_context is not b_target.unit.construction_context

    # Discrimination: the two projects are as alias-prone as they can be -- same
    # module name, same exported name, same source bytes, same artifact CID --
    # and still nothing crosses.
    assert a[0].distribution_artifact_cid == b[0].distribution_artifact_cid
    assert set(session_a.frame_results) == set(session_b.frame_results)


# ---------------------------------------------------------------- twin 8


def test_memo_disablement_changes_performance_only(tmp_path: Path) -> None:
    """The load-bearing law: a memo that changes an answer is not a memo."""
    project = _project(tmp_path, "p", _IMPL_A)

    enabled = SourceResolutionSession(enabled=True)
    disabled = SourceResolutionSession(enabled=False)

    with _MaterializeCounter() as enabled_counter:
        first_enabled = _verdict(project, enabled)
        second_enabled = _verdict(project, enabled)

    with _MaterializeCounter() as disabled_counter:
        first_disabled = _verdict(project, disabled)
        second_disabled = _verdict(project, disabled)

    # Formulas, gaps and verdicts are identical under both settings.
    assert first_enabled == second_enabled == first_disabled == second_disabled

    # Discrimination: disablement is real -- it costs work, and only work.
    assert not disabled.export_resolutions and not disabled.frame_results
    assert disabled_counter.count > enabled_counter.count, (
        f"disabled did {disabled_counter.count} materializations vs enabled "
        f"{enabled_counter.count}; the switch is not doing anything"
    )


# --------------------------------------------------- gaps are memoized too


def test_disablement_preserves_parked_obligation_verdicts(tmp_path: Path) -> None:
    """A parked gap answers identically warm, cold, and with the memo off."""
    root = tmp_path / "gap"
    _install(root, implementation_source="def build(value):\n    return other(value)\n")
    distribution = importlib.metadata.Distribution.at(
        root / "example_dist-1.0.dist-info"
    )
    graph = DependencyArtifactGraph.authenticate(distribution)
    receipt = _receipt(root)

    def answer(session):
        resolved = resolve_import_binding(receipt, graph=graph, session=session)
        assert isinstance(resolved, ResolvedPythonObjectV1)
        projected = resolve_source_visible_frame(resolved, graph=graph, session=session)
        assert isinstance(projected, tuple), projected
        frame, target = projected
        obligations = tuple(
            sorted(
                target.unit.construction_context.opaque_source_call_obligations.values(),
                key=lambda obligation: repr(obligation.coordinate),
            )
        )
        return frame.frame_cid, target.name, obligations

    warm_session = SourceResolutionSession()
    first_warm = answer(warm_session)
    second_warm = answer(warm_session)
    cold = answer(SourceResolutionSession())
    off = answer(SourceResolutionSession(enabled=False))

    assert first_warm == second_warm == cold == off
    assert len(first_warm[2]) == 1
    assert first_warm[2][0].resolution_kind == "call-target-source-absent"
    assert first_warm[2][0].target_name == "other"


# ------------------------------------------------- both sides of the door
#
# The twins above are only worth their runtime if they fail when the memo is
# put back into a shape this repair forbids.  These two tests run the other
# side of that discriminator in-process, so the bite is executable rather than
# asserted in a commit message.


@pytest.fixture
def leaky_process_memo(monkeypatch):
    """Restore the defect: every session shares ONE set of process-wide tables."""
    exports: dict = {}
    frames: dict = {}
    holds: dict = {}
    active: set = set()

    def leaky_init(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.export_resolutions = exports
        self.frame_results = frames
        self.frame_holds = holds
        self.frame_active = active

    monkeypatch.setattr(SourceResolutionSession, "__init__", leaky_init)


@pytest.fixture
def authority_blind_key(monkeypatch):
    """Restore the other defect: a key that forgot an authenticated input."""

    def strip(key):
        return key[1:]  # drop distribution_artifact_cid

    monkeypatch.setattr(
        SourceResolutionSession,
        "export_hit",
        lambda self, key: (
            self.export_resolutions.get(strip(key)) if self.enabled else None
        ),
    )
    monkeypatch.setattr(
        SourceResolutionSession,
        "remember_export",
        lambda self, key, result: (
            self.export_resolutions.__setitem__(strip(key), result)
            if self.enabled
            else None
        ),
    )
    monkeypatch.setattr(
        SourceResolutionSession,
        "frame_hit",
        lambda self, key: self.frame_results.get(strip(key)) if self.enabled else None,
    )
    monkeypatch.setattr(
        SourceResolutionSession,
        "remember_frame",
        lambda self, key, result, hold=None: (
            self.frame_results.__setitem__(strip(key), result) if self.enabled else None
        ),
    )


def test_process_wide_memo_leaks_one_project_into_another(
    tmp_path: Path, leaky_process_memo
) -> None:
    """DISCRIMINATION for twins 1/6/7/8: shared tables serve a foreign context."""
    a = _project(tmp_path, "a", _IMPL_A)
    b = _project(tmp_path, "b", _IMPL_A)

    _verdict(a, SourceResolutionSession())
    with _MaterializeCounter() as counter:
        _verdict(b, SourceResolutionSession())

    assert counter.count == 0, (
        "the leaky shape was expected to serve project B from project A's "
        "materialization; if this no longer reproduces, the twins guarding it "
        "have stopped biting and must be re-derived"
    )


def test_authority_blind_key_aliases_two_distributions(
    tmp_path: Path, authority_blind_key
) -> None:
    """DISCRIMINATION for twins 2/3/4/5: dropping the authority aliases them."""
    session = SourceResolutionSession()
    left_project = _project(tmp_path, "left", _IMPL_A)
    right_project = _project(tmp_path, "right", _IMPL_B)

    left = _resolve(left_project, session)
    right = _resolve(right_project, session)

    assert left.definition.fragment_cid == right.definition.fragment_cid, (
        "a key missing distribution_artifact_cid was expected to serve the "
        "left distribution's definition for the right one; if it no longer "
        "does, the twins guarding the key have stopped biting"
    )
    # The forged answer still carries the WRONG artifact authority, which the
    # downstream projection floor then refuses rather than constructing.  A
    # wrong memo does not get to be quiet: it becomes a gap.
    assert right.distribution_artifact_cid != (
        right_project[0].distribution_artifact_cid
    )
    projected = resolve_source_visible_frame(
        right, graph=right_project[0], session=session
    )
    assert isinstance(projected, mc.ManagerConstructionGapV1)
    assert projected.kind == "artifact-mismatch"
