"""The roll call / minority report -- Phase 1, clean room.

Every test here builds the report from source + a STUB attendance (a plain
dict). No reporter, no ``sugar()``, no construction is stood up anywhere. That
triviality IS the point: reporting is decoupled from constructs except by the
``Attendance`` interface, so the accounting mechanism is testable in total
isolation.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile
from sugar_source_tree.roll_call import (
    Answer,
    EmptyAttendance,
    MappingAttendance,
    MinorityReport,
    function_roster,
    minority_report,
    total_R,
)


def _sf(src: str) -> SourceFile:
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(src)
    f.close()
    return SourceFile(path_source(f.name))  # NO reporter -- the clean room


_THREE = "def a(z):\n    return z\ndef b():\n    return 1\ndef c():\n    pass\n"


def test_roster_is_pure_source_enumeration() -> None:
    # Who SHOULD show up: every function, from the oracle, keyed by CID. No
    # construction consulted.
    roster = function_roster(_sf(_THREE))
    assert [e.name for e in roster] == ["a", "b", "c"]
    assert all(e.cid.startswith("blake3-512:") for e in roster)


def test_moment_zero_minority_is_the_whole_roster() -> None:
    # With nobody having answered, the minority is everyone: the honest
    # "accounted for nothing yet" -- total and truthful before any reporter.
    report = minority_report(_sf(_THREE))  # EmptyAttendance by default
    assert isinstance(report.attendance, EmptyAttendance)
    assert report.R == 3
    assert not report.is_clean
    assert {e.name for e in report.minority} == {"a", "b", "c"}
    assert report.present == ()


def test_threading_attendance_only_shrinks_the_minority() -> None:
    sf = _sf(_THREE)
    roster = function_roster(sf)
    att = MappingAttendance(
        {roster[0].cid: Answer.PRESENT_FACT, roster[2].cid: Answer.PRESENT_INERT}
    )
    report = minority_report(sf, att)
    # present-fact and present-inert both count as SHOWED UP.
    assert {e.name for e in report.present} == {"a", "c"}
    # b never answered -> absent, by difference (b never reported itself).
    assert [e.name for e in report.minority] == ["b"]
    assert report.R == 1


def test_present_inert_is_showing_up_not_absence() -> None:
    # A unit that states nothing still ANSWERED: it is accounted, not minority.
    sf = _sf(_THREE)
    roster = function_roster(sf)
    inert = MappingAttendance({e.cid: Answer.PRESENT_INERT for e in roster})
    assert minority_report(sf, inert).R == 0


def test_explicit_absent_answer_stays_in_the_minority() -> None:
    # An entry that loudly answered ABSENT is still minority (Yellow) -- present
    # is only fact/inert.
    sf = _sf(_THREE)
    roster = function_roster(sf)
    att = MappingAttendance({roster[0].cid: Answer.ABSENT})
    report = minority_report(sf, att)
    assert roster[0] in report.minority
    assert report.R == 3


def test_R_zero_iff_no_minority() -> None:
    sf = _sf(_THREE)
    roster = function_roster(sf)
    full = MappingAttendance({e.cid: Answer.PRESENT_FACT for e in roster})
    report = minority_report(sf, full)
    assert report.R == 0
    assert report.is_clean


def test_roster_is_deterministic_and_content_addressed() -> None:
    # Same source -> same roster CIDs (the oracle's hash), every time.
    a = [e.cid for e in function_roster(_sf(_THREE))]
    b = [e.cid for e in function_roster(_sf(_THREE))]
    assert a == b


def test_total_R_sums_the_whole_minority() -> None:
    reports = [minority_report(_sf(_THREE)), minority_report(_sf("def x():\n    return 0\n"))]
    assert total_R(reports) == 4  # 3 + 1, all moment-zero minority


def test_report_depends_only_on_the_attendance_interface() -> None:
    # A hand-rolled Attendance (anything implementing answer_for) works -- the
    # report never reaches past the interface into construction.
    sf = _sf(_THREE)
    roster = function_roster(sf)

    class OnlyA:
        def answer_for(self, entry):
            return Answer.PRESENT_FACT if entry.name == "a" else None

    report = MinorityReport(roster=roster, attendance=OnlyA())
    assert [e.name for e in report.present] == ["a"]
    assert report.R == 2
