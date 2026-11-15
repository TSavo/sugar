"""An unrolled ``for`` evaluates its iterable once, before the first item (#7757).

A ``for`` over a ground iterable unrolls into its items (``_concrete_elements``)
and consumed the iterable by its ground value without building it: the
``range(...)`` call was a dropped evaluation, and the list display was never
answered (the board's first absentees ``tests/tseries/offsets/test_week.py:110:19``
``for day in range(1, 8)`` (``Call``), ``core/indexes/datetimes.py:99:23``
``for key in ["tz", "freq"]`` (``List``)).  The unrolled loop now opens with the
``range(...)`` call as a statement, every face of it the loop's
(``For._iterable_evaluated``), and a display it consumes member by member
answers with it.
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


def test_a_ground_range_iterable_is_built():
    report = _report(
        "def f(g):\n    for day in range(1, 3):\n        g(day)\n    return g\n"
    )
    present = {(e.kind, e.start_line, e.start_col) for e in report.present}
    assert ("Call", 2, 15) in present
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert ("Call", 2, 15) not in absent


def test_a_display_iterable_answers_with_the_loop():
    report = _report(
        "def f(g):\n    for key in ['tz', 'freq']:\n        g(key)\n    return g\n"
    )
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert ("List", 2, 15) not in absent
