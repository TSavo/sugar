"""An annotated assignment's unevaluated annotation answers the roll (#7757).

``cols: npt.NDArray[np.object_]`` in a class body under ``from __future__
import annotations`` (``io/formats/csvs.py:57``) evaluates no part of its
annotation, and neither does any annotation in a function body or a string
annotation.  The statement built none of it and nothing answered for it (the
board's ``Subscript`` / ``Attribute`` / ``Name`` first absentees after #8349).
Every node of it answers inert with the statement
(``AnnAssign.unevaluated_parts``).
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


def test_a_postponed_class_body_annotation_answers_the_roll():
    report = _report(
        "from __future__ import annotations\n"
        "\n"
        "\n"
        "class C:\n"
        "    cols: list[Missing]\n"
    )
    assert not [
        e
        for e in report.minority
        if e.start_line == 5 and e.kind in ("Name", "Subscript")
    ]


def test_a_string_annotation_answers_the_roll():
    report = _report('x: "Missing" = 1\n')
    assert not [
        e for e in report.minority if e.start_line == 1 and e.kind == "Constant"
    ]
