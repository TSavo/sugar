"""The minority report -- a view over the ONE roll-call interface.

There is one interface: ``reporter.AuditReporter``, threaded through
construction and collected by ``CollectingReporter``. The report reads it; there
is no second interface. These tests fill a ``CollectingReporter`` (by
construction, or by hand through the same interface) and assert the view.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.reporter import CollectingReporter, NullReporter
from sugar_source_tree.tree import SourceFile
from sugar_source_tree.roll_call import (
    MinorityReport,
    minority_report,
    roster_entry_for,
    total_R,
)


def _sf(src: str, reporter) -> SourceFile:
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(src)
    f.close()
    return SourceFile(path_source(f.name), reporter=reporter)


_THREE = "def a(z):\n    return z\ndef b():\n    return 1\ndef c():\n    pass\n"


def test_construction_registers_every_node_through_the_one_interface() -> None:
    # The roster IS what construction registered: no separate enumeration, no
    # second interface -- the reporter threaded through construction holds it.
    r = CollectingReporter()
    report = minority_report(_sf(_THREE, r))
    # roster dedupes by CID; the lazy tree registers a node many times.
    assert 0 < len(report.roster) <= len(r.registered)
    assert len({e.cid for e in report.roster}) == len(report.roster)  # unique
    assert len(report.roster) > 3  # every node, not just the three functions


def test_moment_zero_minority_is_the_whole_roster() -> None:
    # Registered but nothing discharged yet -> the minority is everyone: the
    # honest "accounted for nothing yet."
    r = CollectingReporter()
    report = minority_report(_sf(_THREE, r))
    assert report.R == len(report.roster)
    assert not report.is_clean
    assert report.present == ()


def test_present_discharge_shrinks_the_minority() -> None:
    # Answer present through the SAME interface construction uses; the minority
    # shrinks by exactly those nodes.
    r = CollectingReporter()
    report = minority_report(_sf(_THREE, r))
    a, b = r.registered[0], r.registered[1]
    r.present_fact(a)
    r.present_inert(b)  # present-inert also counts as showed up
    present_cids = {e.cid for e in report.present}
    assert present_cids == {roster_entry_for(a).cid, roster_entry_for(b).cid}
    assert report.R == len(report.roster) - 2


def test_R_zero_iff_no_minority() -> None:
    r = CollectingReporter()
    report = minority_report(_sf(_THREE, r))
    for node in list(r.registered):
        r.present_fact(node)
    assert report.R == 0
    assert report.is_clean


def test_report_is_only_a_view_no_construction_needed() -> None:
    # Fill a CollectingReporter BY HAND through the one interface -- no lift, no
    # SourceFile. The report is a pure view over the collected roll.
    class _FakeNode:
        def __init__(self, cid):
            self._cid = cid

        @property
        def fragment(self):
            outer = self

            class _Seal:
                cid = outer._cid

            class _Frag:
                def seal(self_):
                    return _Seal()

            return _Frag()

        def line_col_span(self):
            class _LC:
                start_line = 1
                start_col = 0

            return _LC()

        kind = "Name"
        name = "x"

        class unit:
            filename = "m.py"

    r = CollectingReporter()
    n1, n2 = _FakeNode("cid1"), _FakeNode("cid2")
    r.register(n1)
    r.register(n2)
    r.present_fact(n1)
    report = MinorityReport(reporter=r)
    assert {e.cid for e in report.present} == {"cid1"}
    assert {e.cid for e in report.minority} == {"cid2"}
    assert report.R == 1


def test_null_reporter_still_satisfies_construction() -> None:
    # A NullReporter is a valid roll-call interface (no-op); construction with it
    # is still complete -- the node is required to carry SOME interface.
    sf = _sf(_THREE, NullReporter())
    assert list(sf.nodes())  # constructs fine


def test_total_R_sums_the_whole_minority() -> None:
    r1, r2 = CollectingReporter(), CollectingReporter()
    reps = [minority_report(_sf(_THREE, r1)), minority_report(_sf("x = 1\n", r2))]
    # moment zero: nothing discharged, so each minority IS its whole (deduped)
    # roster.
    assert total_R(reps) == len(reps[0].roster) + len(reps[1].roster)


def test_the_roster_covers_every_source_line() -> None:
    # Totality: every source line is spanned by a registered node, so every line
    # is accounted (present) or in the minority (absent) -- never unpainted.
    src = (
        "def a(z):\n"
        "    x = z + 1\n"
        "    return x\n"
        "\n"
        "def b():\n"
        "    with open('p'):\n"
        "        pass\n"
    )
    r = CollectingReporter()
    sf = _sf(src, r)
    list(sf.nodes())
    code_lines = {i for i, ln in enumerate(src.splitlines(), 1) if ln.strip()}
    covered: set[int] = set()
    for node in r.registered:
        lc = node.line_col_span()
        covered |= set(range(lc.start_line, lc.end_line + 1))
    assert not (code_lines - covered)


def test_discharge_produces_the_true_minority_written_vs_not() -> None:
    # The whole loop: construction REGISTERS (constructor), discharge ANSWERS
    # present (template) or absent (abstract). A written function's nodes
    # discharge present; an unwritten construct (Delete has no sugar) and its
    # ancestors stay in the minority -- red until written.
    from sugar_source_tree.roll_call import discharge

    r = CollectingReporter()
    report = discharge(_sf("def a(z):\n    return z\ndef b(xs):\n    del xs\n", r))
    kinds_present = {e.kind for e in report.present}
    kinds_absent = {e.kind for e in report.minority}
    assert "Return" in kinds_present  # a's body desugared
    assert "Delete" in kinds_absent  # the unwritten construct is minority
    assert not report.is_clean  # R > 0 while anything is unwritten
