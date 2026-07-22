"""The roll call / minority report -- Phase 1, clean room.

Every test here builds the report from source + a STUB attendance (a plain
dict). No reporter, no ``sugar()``, no construction is stood up anywhere. That
triviality IS the point: reporting is decoupled from constructs except by the
``Attendance`` interface, so the accounting mechanism is testable in total
isolation.

ONE roster: every node, keyed by its fragment CID. "Functions construct clean"
is a query over it, never a second roster.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile
from sugar_source_tree.roll_call import (
    Answer,
    EmptyAttendance,
    MappingAttendance,
    MinorityReport,
    minority_report,
    roster,
    total_R,
)


def _sf(src: str) -> SourceFile:
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(src)
    f.close()
    return SourceFile(path_source(f.name))  # NO reporter -- the clean room


_THREE = "def a(z):\n    return z\ndef b():\n    return 1\ndef c():\n    pass\n"


def _fn_names(entries):
    return [e.name for e in entries if e.kind in ("FunctionDef", "AsyncFunctionDef")]


def test_roster_is_pure_source_enumeration_of_every_node() -> None:
    # ONE roster: every node, keyed by CID. The functions are a query over it.
    r = roster(_sf(_THREE))
    assert len(r) > 3  # far more than three: every node, not just functions
    assert _fn_names(r) == ["a", "b", "c"]
    assert all(e.cid.startswith("blake3-512:") for e in r)


def test_moment_zero_minority_is_the_whole_roster() -> None:
    # Nobody answered -> the minority is everyone: the honest "accounted for
    # nothing yet," total and truthful before any reporter.
    report = minority_report(_sf(_THREE))  # EmptyAttendance by default
    assert isinstance(report.attendance, EmptyAttendance)
    r = roster(_sf(_THREE))
    assert report.R == len(r)
    assert not report.is_clean
    assert report.present == ()


def test_threading_attendance_only_shrinks_the_minority() -> None:
    sf = _sf(_THREE)
    r = roster(sf)
    att = MappingAttendance(
        {r[0].cid: Answer.PRESENT_FACT, r[1].cid: Answer.PRESENT_INERT}
    )
    report = minority_report(sf, att)
    # present-fact and present-inert both count as SHOWED UP.
    assert set(report.present) == {r[0], r[1]}
    # everyone else never answered -> absent, by difference.
    assert report.R == len(r) - 2
    assert r[0] not in report.minority and r[1] not in report.minority


def test_present_inert_is_showing_up_not_absence() -> None:
    sf = _sf(_THREE)
    inert = MappingAttendance({e.cid: Answer.PRESENT_INERT for e in roster(sf)})
    assert minority_report(sf, inert).R == 0


def test_explicit_absent_answer_stays_in_the_minority() -> None:
    # A loud ABSENT answer is still minority (Yellow) -- present is only
    # fact/inert.
    sf = _sf(_THREE)
    r = roster(sf)
    att = MappingAttendance({r[0].cid: Answer.ABSENT})
    report = minority_report(sf, att)
    assert r[0] in report.minority
    assert report.R == len(r)


def test_R_zero_iff_no_minority() -> None:
    sf = _sf(_THREE)
    full = MappingAttendance({e.cid: Answer.PRESENT_FACT for e in roster(sf)})
    report = minority_report(sf, full)
    assert report.R == 0
    assert report.is_clean


def test_roster_is_deterministic_and_content_addressed() -> None:
    a = [e.cid for e in roster(_sf(_THREE))]
    b = [e.cid for e in roster(_sf(_THREE))]
    assert a == b


def test_total_R_sums_the_whole_minority() -> None:
    reports = [minority_report(_sf(_THREE)), minority_report(_sf("x = 1\n"))]
    assert total_R(reports) == len(roster(_sf(_THREE))) + len(roster(_sf("x = 1\n")))


def test_report_depends_only_on_the_attendance_interface() -> None:
    # A hand-rolled Attendance (anything with answer_for) works -- the report
    # never reaches past the interface into construction.
    sf = _sf(_THREE)
    r = roster(sf)
    first = r[0]

    class OnlyFirst:
        def answer_for(self, entry):
            return Answer.PRESENT_FACT if entry.cid == first.cid else None

    report = MinorityReport(roster=r, attendance=OnlyFirst())
    assert report.present == (first,)
    assert report.R == len(r) - 1


def test_the_roster_covers_every_source_line() -> None:
    # The totality law: every line of source is spanned by some roster node, so
    # every line is accounted (present) or in the minority (absent) -- never a
    # third, unpainted state. Coverage is a property of the roster, not a check.
    src = (
        "def a(z):\n"
        "    x = z + 1\n"
        "    return x\n"
        "\n"
        "def b():\n"
        "    with open('p'):\n"
        "        pass\n"
    )
    sf = _sf(src)
    code_lines = {i for i, ln in enumerate(src.splitlines(), 1) if ln.strip()}
    covered: set[int] = set()
    for node in sf.nodes():
        lc = node.line_col_span()
        covered |= set(range(lc.start_line, lc.end_line + 1))
    assert not (code_lines - covered)  # zero unaccounted lines
