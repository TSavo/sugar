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
"""

from __future__ import annotations

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


def _report(reporter: CollectingReporter) -> MinorityReport:
    handle = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    handle.write(_THREE)
    handle.close()
    return minority_report(
        SourceFile(
            path_source(handle.name),
            reporter=reporter,
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )


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
