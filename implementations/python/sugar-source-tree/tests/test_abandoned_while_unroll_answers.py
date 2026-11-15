"""What an abandoned ``while`` unroll made answers the roll where it was made
(#7757).

``While._try_unroll`` substitutes the test in the state before the loop to
decide it by a ground value.  Where no ground value decides it, the attempt
is given up and the loop stays live, substituted afresh.  The test copy it
made -- a formal the loop carries, re-spanned to its read -- was built by
nothing: ``core/_numba/kernels/min_max_.py`` (``while lo < hi`` over the
formal ``lo``) ended in ``FormalRef`` and ``BindingCoordinateRef registered
but never answered the roll call`` on the pandas board at ``d54a43717``
(run 43739300912).  The live loop reads ``lo`` through its header's
evaluation, a node of another kind at that span, so nothing answered for
the copy.  ``while True`` given up at the guard of its ``break`` left what
it substituted before the guard the same way (``tests/io/test_common.py``,
``core/sorting.py``, ``io/parsers/python_parser.py``).
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _report(source: str):
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(source)
    f.close()
    return discharge(
        SourceFile(
            path_source(f.name),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )


def test_a_live_while_over_a_carried_formal_leaves_no_absentee():
    report = _report(
        "def bisect_left(a, x, lo=0, hi=-1):\n"
        "    if hi == -1:\n"
        "        hi = len(a)\n"
        "    while lo < hi:\n"
        "        mid = (lo + hi) // 2\n"
        "        if a[mid] < x:\n"
        "            lo = mid + 1\n"
        "        else:\n"
        "            hi = mid\n"
        "    return lo\n"
    )
    assert not any(
        e.kind in ("FormalRef", "BindingCoordinateRef") and e.start_line == 4
        for e in report.minority
    ), report.minority


def test_a_while_true_given_up_at_its_break_guard_leaves_no_absentee():
    # ``while True`` is ground, so the unroll substitutes the first item
    # until the guard of its ``break``, which no ground value decides
    # (``tests/io/test_common.py:131``, ``core/sorting.py:185``): what it
    # substituted before giving up answers where it was made.
    report = _report(
        "def f(read, n):\n"
        "    out = 0\n"
        "    while True:\n"
        "        chunk = read(n)\n"
        "        out += len(chunk)\n"
        "        if len(chunk) < n:\n"
        "            break\n"
        "    return out\n"
    )
    assert not any(
        e.kind == "EvaluationRef" and e.start_line in (5, 6)
        for e in report.minority
    ), report.minority
