"""A loop's, a comprehension's and an unpack's iterable is built (#7757).

Python evaluates a ``for``'s iterable once, before the first item; a
comprehension's outermost iterable once, before the first element; an
unpack's right-hand side once, before any target is bound.  Each is built
as a node of its own and answers the roll where it stands: the
``range(...)`` call is never a dropped evaluation, and a display iterable
answers with the loop (the board's first absentees
``tests/tseries/offsets/test_week.py:110:19`` ``for day in range(1, 8)``
(``Call``), ``core/indexes/datetimes.py:99:23`` ``for key in ["tz",
"freq"]`` (``List``)).

This file once pinned the unroll of a ``for`` and the dissolution of a
comprehension into its display, both deleted (#8957: the comprehension is
the one recurrence, ``ComprehensionSugar``).  What it states now is what
the one way owes: every iterable is built.  An unpack whose right-hand side
holds a comprehension at a level substitution cannot pair
(``a, (b, c) = 1, [x for x in range(2)]``) takes the reduce-time unpack of
the statement's one evaluation (``Assign._dynamic_unpack_target``), so the
``range(2)`` call is built there, never refused with the statement
(#7757 S2).
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
def test_a_comprehension_builds_its_range_iterable(comprehension):
    # The comprehension is the one recurrence: its outermost iterable is
    # evaluated once, before the first element, and built (#7757).
    report = _report(f"def f():\n    return {comprehension}\n")
    column = comprehension.index("range")
    present = {(e.kind, e.start_line, e.start_col) for e in report.present}
    assert ("Call", 2, 11 + column) in present
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert ("Call", 2, 11 + column) not in absent


def test_a_loop_over_a_comprehension_builds_its_iterable():
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
def test_a_comprehension_over_a_range_answers(comprehension):
    # However many items the range holds, and whether or not a key is
    # decided, the comprehension answers where it stands.
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
def test_a_template_never_evaluated_answers_with_the_comprehension(
    comprehension, kind, column
):
    # ``core/_numba/kernels/mean_.py:161``: Python evaluates no element of
    # an empty iteration (nor a filter where there is no item); the template
    # answers with the comprehension it belongs to.
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
def test_a_comprehension_builds_each_member_of_its_display_iterable(
    comprehension,
):
    # Python evaluates every member of the iterable display before the first
    # element: each member that calls is built once.
    report = _report(f"def f():\n    return {comprehension}\n")
    column = 11 + comprehension.index("abs(2)")
    present = {(e.kind, e.start_line, e.start_col) for e in report.present}
    assert ("Call", 2, column) in present
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert ("Call", 2, column) not in absent
    assert not any(e.kind == "EvaluationRef" for e in report.minority)


@pytest.mark.parametrize(
    "statement",
    [
        "a, b = [x for x in range(2)]",
        "a, (b, c) = 1, [x for x in range(2)]",
        "a, *b = [x for x in range(3)]",
    ],
)
def test_an_unpack_of_a_comprehension_builds_its_iterable(statement):
    # The unpack evaluates its right-hand side once and unpacks the value at
    # reduce: the comprehension, a nested level of a display among them, is
    # built, and so is its ``range(...)`` call (#7757 S2).
    report = _report(f"def f():\n    {statement}\n    return a\n")
    column = 4 + statement.index("range")
    present = {(e.kind, e.start_line, e.start_col) for e in report.present}
    assert ("Call", 2, column) in present
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert ("Call", 2, column) not in absent


@pytest.mark.parametrize("iterable", ["range(0)", "[]"])
def test_an_empty_iteration_s_body_answers_with_the_loop(iterable):
    # Python evaluates no item of an empty iterable: the body and the target
    # are never evaluated, and answer with the loop.
    report = _report(
        f"def f(g):\n    for day in {iterable}:\n        g(day + 1)\n    return g\n"
    )
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert not any(line == 3 for _kind, line, _col in absent), absent
    assert ("Name", 2, 8) not in absent


def test_a_display_iterable_answers_with_the_loop():
    report = _report(
        "def f(g):\n    for key in ['tz', 'freq']:\n        g(key)\n    return g\n"
    )
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert ("List", 2, 15) not in absent
