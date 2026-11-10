"""The minority report reads each answer on the roll once.

``roster``, ``present``, ``minority`` and ``R`` are all questions about the
same two append-only rolls. Every question used to re-derive a roster entry
for every registration (seven whole-roll passes for one file's audit). The
view now indexes each answer once and reads only what was appended since.

Twins:
  truthful — any number of questions derives one entry per answer, the
             answers equal a fresh view's, and an answer appended after a
             question is seen by the next one;
  lying    — a roll that was replaced or shortened is not answered from the
             index of the roll it replaced.

One logical node answers through many shells. A shell whose fragment and kind
were already read on the roll is the same answer and derives nothing.

Twins:
  truthful — any number of shells of one logical node derives one entry;
  lying    — equal text at two loci stays two entries, two kinds over one
             span stay two entries, and one span of one filename over two
             texts stays two entries.
"""

from __future__ import annotations

import dataclasses
import tempfile

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree import roll_call
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import MinorityReport, minority_report
from sugar_source_tree.tree import SourceFile

_THREE = "def a(z):\n    return z\ndef b():\n    return 1\ndef c():\n    pass\n"


def _path(text: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    handle.write(text)
    handle.close()
    return handle.name


def _report_at(path: str, reporter: CollectingReporter) -> MinorityReport:
    return minority_report(
        SourceFile(
            path_source(path),
            reporter=reporter,
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )


def _report(reporter: CollectingReporter, text: str = _THREE) -> MinorityReport:
    return _report_at(_path(text), reporter)


@pytest.fixture
def derivations(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    count = [0]
    derive = roll_call.roster_entry_for

    def counted(node):
        count[0] += 1
        return derive(node)

    monkeypatch.setattr(roll_call, "roster_entry_for", counted)
    return count


def _answers(report: MinorityReport) -> tuple:
    return (report.roster, report.present, report.minority, report.R)


def test_every_question_together_derives_one_entry_per_answer(
    derivations: list[int],
) -> None:
    reporter = CollectingReporter()
    report = _report(reporter)
    reporter.present_fact(reporter.registered[0])
    derivations[0] = 0

    first = _answers(report)
    assert derivations[0] == len(reporter.registered) + len(reporter.present)

    assert _answers(report) == first
    assert derivations[0] == len(reporter.registered) + len(reporter.present)

    assert first == _answers(MinorityReport(reporter=reporter))


def test_an_answer_appended_after_a_question_is_seen_by_the_next(
    derivations: list[int],
) -> None:
    reporter = CollectingReporter()
    report = _report(reporter)
    before = report.R
    assert before == len(report.roster)
    derivations[0] = 0

    reporter.present_fact(reporter.registered[0])
    assert report.R == before - 1
    # Only the one appended answer was read.
    assert derivations[0] == 1
    assert _answers(report) == _answers(MinorityReport(reporter=reporter))


def test_a_replaced_roll_is_not_answered_from_the_old_index() -> None:
    reporter = CollectingReporter()
    report = _report(reporter)
    for node in list(reporter.registered):
        reporter.present_fact(node)
    assert report.is_clean

    # The same length, a different roll: nobody showed up on this one.
    reporter.present = []
    assert report.present == ()
    assert report.R == len(report.roster)
    assert not report.is_clean


def test_a_shortened_roll_is_read_again_from_its_first_answer() -> None:
    reporter = CollectingReporter()
    report = _report(reporter)
    whole = report.roster
    assert len(whole) > 3

    del reporter.registered[1:]
    assert report.roster == MinorityReport(reporter=reporter).roster
    assert len(report.roster) == 1


def test_many_shells_of_one_logical_node_derive_one_entry(
    derivations: list[int],
) -> None:
    reporter = CollectingReporter()
    whole = _report(reporter).roster
    logical = derivations[0]
    assert logical == len(whole)

    # Three more shells of every node: the same ref, a new object each.
    for node in list(reporter.registered):
        for _ in range(3):
            shell = dataclasses.replace(node)
            assert shell is not node
            if reporter.registered[-1] is not shell:
                reporter.register(shell)
    assert len(reporter.registered) >= 4 * logical

    derivations[0] = 0
    assert MinorityReport(reporter=reporter).roster == whole
    assert derivations[0] == logical


def test_equal_text_at_two_loci_stays_two_entries() -> None:
    report = _report(CollectingReporter(), "x = 1\nx = 1\n")
    assigns = [e for e in report.roster if e.kind == "Assign"]
    assert len(assigns) == 2
    assert assigns[0].cid == assigns[1].cid
    assert assigns[0].start_line != assigns[1].start_line


def test_two_kinds_over_one_span_stay_two_entries() -> None:
    report = _report(CollectingReporter(), "x\n")
    over_x = {e.kind: e for e in report.roster if e.kind in ("Expr", "Name")}
    assert set(over_x) == {"Expr", "Name"}
    expr, name = over_x["Expr"], over_x["Name"]
    assert (expr.cid, expr.start_line, expr.start_col) == (
        name.cid,
        name.start_line,
        name.start_col,
    )


def test_one_span_of_one_filename_over_two_texts_stays_two_entries() -> None:
    reporter = CollectingReporter()
    path = _path("a\n")
    _report_at(path, reporter)
    with open(path, "w") as handle:
        handle.write("b\n")
    report = _report_at(path, reporter)
    names = [e for e in report.roster if e.kind == "Name"]
    assert len(names) == 2
    assert {e.file for e in names} == {path}
    assert len({(e.start_line, e.start_col) for e in names}) == 1
    assert len({e.cid for e in names}) == 2
