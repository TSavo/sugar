# SPDX-License-Identifier: MIT OR Apache-2.0
"""SIN CLUSTER 7: source-audit presence is keyed by the full roll-call identity.

``MinorityReport`` partitions present/minority by
``(file, line, col, kind, cid)``. Equal source text seals to one CID at
distinct loci; those seats are distinct obligations. Keying source-audit
status by CID alone promotes every seat that shares a present CID to Blue
while ``report.R`` still counts the absent seat — so
``warranted + unresolved`` can exceed ``source_loci``, and Yellow silently
becomes Blue.

Truthful twin: full-tuple presence, conservation holds.
Lying twin: shared CID, present at one locus and absent at the other, must
NOT mark both warranted — red against the dual CID-only producers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import MinorityReport
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1


class _Seat:
    """Minimal node seat: sealed CID + source coordinate + kind."""

    def __init__(
        self,
        cid: str,
        *,
        line: int,
        col: int,
        kind: str = "Name",
        name: str = "x",
        file: str = "t.py",
    ) -> None:
        self._cid = cid
        self._line = line
        self._col = col
        self.kind = kind
        self.name = name

        class _Unit:
            filename = file

        self.unit = _Unit()

    @property
    def fragment(self):
        outer = self

        class _Seal:
            @property
            def cid(self_):
                return outer._cid

        class _Frag:
            def seal(self_):
                return _Seal()

        return _Frag()

    def line_col_span(self):
        outer = self

        class _LC:
            start_line = outer._line
            start_col = outer._col
            end_line = outer._line
            end_col = outer._col + 1

        return _LC()


def _split_presence_report() -> MinorityReport:
    """Same CID at two loci; only the first discharges present."""
    r = CollectingReporter()
    a = _Seat("shared-cid", line=1, col=0)
    b = _Seat("shared-cid", line=2, col=0)
    r.register(a)
    r.register(b)
    r.present_fact(a)
    report = MinorityReport(reporter=r)
    assert report.R == 1
    assert len(report.roster) == 2
    assert len(report.present) == 1
    assert len(report.minority) == 1
    return report


def _status_by_line(audit: dict) -> dict[int, str]:
    return {row["locus"]["line"]: row["status"] for row in audit["loci"]}


def _assert_conserved(audit: dict, *, report_R: int) -> None:
    """Live ledger tooth — requires report.R, not status-only sum.

    Status-only ``warranted + unresolved == source_loci`` is tautological when
    every locus is binary; it stays green under CID-alone partial presence.
    """
    from sugar_lift_py_tests.tree_enumerate import assert_source_audit_ledger

    totals = audit["totals"]
    assert_source_audit_ledger(
        warranted=totals["source_warranted"],
        unresolved=totals["source_unresolved"],
        source_loci=totals["source_loci"],
        report_R=report_R,
    )


# ---------------------------------------------------------------------------
# Lying twin — MUST fail against the CID-alone dual producers
# ---------------------------------------------------------------------------


def test_lying_twin_shared_cid_partial_presence_does_not_warrant_both() -> None:
    """THE lying twin.

    Present at locus 1, absent at locus 2, same CID. The product must keep
    locus 2 Yellow. CID-alone keying marks both Blue and (on the lift_rpc
    producer) lets warranted + R exceed source_loci.
    """
    from sugar_lift_py_tests.tree_enumerate import source_audit_from_report

    report = _split_presence_report()
    audit = source_audit_from_report(report, "t.py")

    assert _status_by_line(audit) == {
        1: "warranted",
        2: "unresolved",
    }, (
        "shared CID at two loci: present at one must not promote the other; "
        f"got {_status_by_line(audit)}"
    )
    totals = audit["totals"]
    assert totals["source_warranted"] == 1
    assert totals["source_unresolved"] == 1
    assert totals["source_loci"] == 2
    _assert_conserved(audit, report_R=report.R)
    assert totals["source_unresolved"] == report.R


def test_lying_twin_lift_rpc_roll_call_uses_the_one_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """lift_rpc must not re-derive presence by CID; it uses the one door."""
    from sugar_lift_py_tests import lift_rpc
    import sugar_source_tree.roll_call as roll_call

    report = _split_presence_report()
    seats = list(report.reporter.registered)

    class _Unit:
        source_cid = "mod"

    class _SF:
        unit = _Unit()
        reporter = report.reporter

    class _Reporter:
        def __init__(self) -> None:
            self.registered = seats
            self.gaps: list = []
            self.present = list(report.reporter.present)

    # The leaf opens through the CONSTRUCTION door, never `SourceFile.from_path`
    # (a context-less tree paints every With RuntimeSelectedContextManager).
    # Stub that door, so this test still exercises the real projection.
    monkeypatch.setattr(
        lift_rpc, "open_source_file_for_construction", lambda *a, **k: _SF()
    )
    monkeypatch.setattr(roll_call, "discharge", lambda sf: report)
    monkeypatch.setattr("sugar_source_tree.reporter.CollectingReporter", _Reporter)

    path = tmp_path / "t.py"
    path.write_text("# seat file\n", encoding="utf-8")
    leaf = lift_rpc._roll_call_audit_leaf(path, "t.py", root=tmp_path)
    audit = leaf["auxiliaryRows"]["sourceAudit"]

    assert _status_by_line(audit) == {
        1: "warranted",
        2: "unresolved",
    }, f"lift_rpc still keys presence by CID alone: {_status_by_line(audit)}"
    _assert_conserved(audit, report_R=report.R)
    assert audit["totals"]["source_unresolved"] == report.R


# ---------------------------------------------------------------------------
# Truthful twin — full-tuple presence and conservation
# ---------------------------------------------------------------------------


def test_truthful_twin_both_present_both_warranted() -> None:
    from sugar_lift_py_tests.tree_enumerate import source_audit_from_report

    r = CollectingReporter()
    a = _Seat("shared-cid", line=1, col=0)
    b = _Seat("shared-cid", line=2, col=0)
    r.register(a)
    r.register(b)
    r.present_fact(a)
    r.present_fact(b)
    report = MinorityReport(reporter=r)

    audit = source_audit_from_report(report, "t.py")
    assert _status_by_line(audit) == {1: "warranted", 2: "warranted"}
    assert audit["totals"] == {
        "source_loci": 2,
        "source_warranted": 2,
        "source_unresolved": 0,
    }
    _assert_conserved(audit, report_R=report.R)
    assert report.R == 0


def test_truthful_twin_neither_present_both_unresolved() -> None:
    from sugar_lift_py_tests.tree_enumerate import source_audit_from_report

    r = CollectingReporter()
    a = _Seat("shared-cid", line=1, col=0)
    b = _Seat("shared-cid", line=2, col=0)
    r.register(a)
    r.register(b)
    report = MinorityReport(reporter=r)

    audit = source_audit_from_report(report, "t.py")
    assert _status_by_line(audit) == {1: "unresolved", 2: "unresolved"}
    assert audit["totals"] == {
        "source_loci": 2,
        "source_warranted": 0,
        "source_unresolved": 2,
    }
    _assert_conserved(audit, report_R=report.R)
    assert audit["totals"]["source_unresolved"] == report.R


def test_truthful_twin_roll_call_path_conserves_on_real_source(tmp_path: Path) -> None:
    """Live construction path: totals conserve; unresolved matches report.R."""
    from sugar_lift_py_tests.tree_enumerate import source_audit_from_roll_call
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.roll_call import discharge
    from sugar_source_tree.tree import SourceFile

    path = tmp_path / "m.py"
    path.write_text("def f():\n    return 1\n", encoding="utf-8")
    audit = source_audit_from_roll_call(path, "m.py")

    reporter = CollectingReporter()
    report = discharge(
        SourceFile.from_path(
            str(path),
            reporter=reporter,
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    _assert_conserved(audit, report_R=report.R)
    assert audit["totals"]["source_unresolved"] == report.R
    assert audit["totals"]["source_loci"] == len(report.roster)
