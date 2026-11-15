"""An annotation Python evaluates is built where its statement runs (#7757).

Without ``from __future__ import annotations`` Python evaluates a ``def``'s
parameter and return annotations when the ``def`` statement runs, and a
module or class body's annotated name's annotation after its store.  Nothing
built them, so their nodes never answered the roll (the board's ``Name``
first absentees after #8349: ``api/internals.py:15:5``), and ``def f(a:
Missing)`` never raised NameError where the ``def`` runs.  The ``def``
statement evaluates each after its defaults (``_evaluated_annotations``);
an annotated name's annotation is the expression statement spliced after
it (``AnnAssign.substitute``).
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


def test_an_evaluated_def_annotation_answers_by_construction():
    report = _report("def f(a: int, b: int = 1) -> int:\n    return a\n")
    assert not [e for e in report.minority if e.start_line == 1]


def test_an_evaluated_annotated_name_answers_by_construction():
    report = _report("x: int = 1\n\n\nclass C:\n    y: int = 1\n    z: int\n")
    assert not [e for e in report.minority if e.start_line in (1, 5, 6)]
