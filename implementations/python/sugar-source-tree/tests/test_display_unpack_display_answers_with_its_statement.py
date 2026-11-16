"""A display an unpack consumes answers the roll (#7757).

The board's ``Tuple`` first absentees
(``tests/indexes/interval/test_interval_range.py:31:21`` ``start, end = 0,
100``, ``io/formats/console.py:43:42`` ``terminal_width, terminal_height =
None, None``) were displays a substitution-time pairing consumed member by
member and never built.  That pairing is deleted (#7757 S2): the right-hand
side display is built whole, as Python builds it, and the one reduce-time
unpack reads the tuple it reduces to, so the display, every nested level of
it, and its members answer where they stand.
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


def test_a_display_unpack_answers_its_display():
    report = _report(
        "def f(p):\n"
        "    start, end = 0, p\n"
        "    (a, b), c = (start, 1), end\n"
        "    return a + b + c\n"
    )
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    # ``0, p`` at 2:17; ``(start, 1), end`` and ``(start, 1)`` both at 3:16.
    assert ("Tuple", 2, 17) not in absent
    assert ("Tuple", 3, 16) not in absent
    present = {(e.kind, e.start_line, e.start_col) for e in report.present}
    assert {("Constant", 2, 17), ("Constant", 3, 24)} <= present
