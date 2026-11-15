"""A postponed annotation stands as written; substitution mints no read for it (#7757).

Under ``from __future__ import annotations`` (and for a string annotation
anywhere) Python never evaluates a ``def``'s annotations where the statement
runs.  The signature substitution still rewrote a name in one that a module
assignment bound into its re-spanned ``EvaluationRef`` -- a read nothing
constructs, so it never answered (the board's ``EvaluationRef`` first
absentee ``_typing.py:113:54``, ``-> _T_co`` under ``_T_co = TypeVar(...)``).
The annotation now stands as written and answers with its definition
(``unevaluated_parts``).
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def test_a_postponed_annotation_mints_no_read():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(
        "from __future__ import annotations\n"
        "\n"
        "T = int\n"
        "\n"
        "\n"
        "def f(x: T = 1) -> T:\n"
        "    return x\n"
    )
    f.close()
    reporter = CollectingReporter()
    report = discharge(
        SourceFile(
            path_source(f.name),
            reporter=reporter,
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    assert not [
        e
        for e in report.minority
        if e.start_line == 6 and e.kind in ("EvaluationRef", "Name")
    ]
    present = {(e.kind, e.start_line, e.start_col) for e in report.present}
    assert {("Name", 6, 9), ("Name", 6, 19)} <= present
