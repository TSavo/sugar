"""A class docstring answers the roll where the class body consumes it (#7757).

The class statement reads its docstring as ``docstring_cid`` and runs nothing
of it (``ClassDef._class_body_block``), so the ``Expr`` and its constant
registered when the tree was materialized and nothing answered for them (the
board's ``Expr`` first absentees after #8349: ``core/groupby/indexing.py:33``,
``core/arrays/boolean.py:45``).  They answer inert where the body consumed
them, the docstring's reason.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def test_a_class_docstring_answers_the_roll():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write('class C:\n    """Doc."""\n\n    x = 1\n')
    f.close()
    reporter = CollectingReporter()
    report = discharge(
        SourceFile(
            path_source(f.name),
            reporter=reporter,
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    docstring = {
        (e.kind, e.start_line, e.start_col)
        for e in report.present
        if e.kind in ("Expr", "Constant") and e.start_line == 2
    }
    assert docstring == {("Expr", 2, 4), ("Constant", 2, 4)}
    assert not [e for e in report.minority if e.start_line == 2]
