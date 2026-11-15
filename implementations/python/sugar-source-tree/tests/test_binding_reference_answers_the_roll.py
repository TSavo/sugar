"""A binding's evaluation reference answers the roll where it is bound (#7757).

``y = e`` binds ``y`` to its projection of the statement's evaluation, an
``EvaluationRef`` minted at the target's span (``Assign.target_evaluations``).
It is a value of the block's scope: a read of ``y`` is re-spanned to its own
site and answers for itself, so nothing constructs the reference at the
target, and ``__all__ = [...]`` (never read) left it registered and
unanswered: the board's ``EvaluationRef`` first absentees after #8349
(``api/executors/__init__.py:7:0``, ``core/computation/check.py:5:0``).
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def test_a_binding_reference_answers_the_roll():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write('x = 1\ny = x\n__all__ = ["y"]\n')
    f.close()
    reporter = CollectingReporter()
    report = discharge(
        SourceFile(
            path_source(f.name),
            reporter=reporter,
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    assert not [e for e in report.minority if e.kind == "EvaluationRef"]
