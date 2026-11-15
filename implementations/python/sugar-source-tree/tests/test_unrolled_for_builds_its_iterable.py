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

import pytest

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


@pytest.mark.parametrize(
    "comprehension",
    [
        "[x + 1 for x in range(1, 3)]",
        "{x for x in range(1, 3)}",
        "{x: 0 for x in range(1, 3)}",
    ],
)
def test_a_dissolved_comprehension_builds_its_range_iterable(comprehension):
    # The comprehension dissolves into its display through the same step a
    # ``for`` unrolls by (``For._iterable_evaluations``): the ``range(...)``
    # call is evaluated before the first member, never dropped (#7757).
    report = _report(f"def f():\n    return {comprehension}\n")
    column = comprehension.index("range")
    present = {(e.kind, e.start_line, e.start_col) for e in report.present}
    assert ("Call", 2, 11 + column) in present
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert ("Call", 2, 11 + column) not in absent


def test_a_dissolved_comprehension_carries_its_iterable_into_a_loop():
    # A loop over a dissolved display evaluates what the display carried.
    report = _report(
        "def f(g):\n    for k in [x for x in range(2)]:\n        g(k)\n    return g\n"
    )
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert ("Call", 2, 25) not in absent


@pytest.mark.parametrize(
    "comprehension",
    [
        "[str(i) for i in range(200)]",
        '{f"c{i}": 0 for i in range(3)}',
        "[0 for i in range(3)]",
    ],
)
def test_a_range_item_answers_where_it_is_minted(comprehension):
    # Past the unroll fuel no item is minted; an item an unroll that refuses
    # (an undecided dict key) or never reads (an unread target) minted
    # answers where it was minted (``_minted_binding_reference``).
    report = _report(f"def f():\n    return {comprehension}\n")
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert ("Constant", 2, 11) not in absent


@pytest.mark.parametrize(
    ("comprehension", "kind", "column"),
    [
        ("[0 for i in range(0)]", "Constant", 12),
        ("[x + 1 for x in [1, 2] if x > 5]", "BinOp", 12),
        ("{x: x + 1 for x in range(0) if x > 5}", "Compare", 42),
    ],
)
def test_a_template_never_evaluated_answers_with_the_display(
    comprehension, kind, column
):
    # ``core/_numba/kernels/mean_.py:161``: Python evaluates no element of
    # an empty unroll (nor a filter where there is no item); the template
    # answers with the display it dissolved into.
    report = _report(f"def f():\n    return {comprehension}\n")
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert (kind, 2, column) not in absent


@pytest.mark.parametrize(
    "comprehension",
    [
        "[str(x) for x in [abs(1), abs(2)]]",
        "[0 for _ in [abs(1), abs(2)]]",
    ],
)
def test_a_dissolved_comprehension_builds_each_member_before_its_elements(
    comprehension,
):
    # Python evaluates every member of the iterable display before the first
    # element: each member that calls is built once, as an evaluation the
    # display carries (``ListComp._members_evaluated_first``), and the
    # reference the element reads it through answers where it is minted.
    report = _report(f"def f():\n    return {comprehension}\n")
    column = 11 + comprehension.index("abs(2)")
    present = {(e.kind, e.start_line, e.start_col) for e in report.present}
    assert ("Call", 2, column) in present
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert ("Call", 2, column) not in absent
    assert not any(e.kind == "EvaluationRef" for e in report.minority)


def test_a_display_iterable_answers_with_the_loop():
    report = _report(
        "def f(g):\n    for key in ['tz', 'freq']:\n        g(key)\n    return g\n"
    )
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert ("List", 2, 15) not in absent
