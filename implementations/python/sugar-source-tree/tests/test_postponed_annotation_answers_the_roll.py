"""A postponed annotation answers the roll with its ``def`` (#7757).

Under ``from __future__ import annotations`` (PEP 563) no annotation is
evaluated where the ``def`` statement runs, and a string annotation is never
evaluated as the type it names.  The ``def`` statement built none of them and
nothing answered for them (the board's ``Name`` first absentees after #8349:
``core/reshape/pivot.py:68:5``'s ``-> DataFrame``).  They answer inert with
the statement, that reason (``Node.unevaluated_parts``).  An annotation
Python does evaluate where the statement runs is not answered here.
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
    reporter = CollectingReporter()
    return discharge(
        SourceFile(
            path_source(f.name),
            reporter=reporter,
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )


def test_a_postponed_annotation_answers_with_its_def():
    report = _report(
        "from __future__ import annotations\n"
        "\n"
        "\n"
        "def f(a: list[Missing], b: int = 1) -> Missing:\n"
        "    return a\n"
    )
    assert not [
        e
        for e in report.minority
        if e.start_line == 4 and e.kind in ("Name", "Subscript")
    ]


def test_a_string_annotation_answers_with_its_def():
    report = _report('def f(a: "Missing") -> "Missing":\n    return a\n')
    assert not [
        e for e in report.minority if e.start_line == 1 and e.kind == "Constant"
    ]
