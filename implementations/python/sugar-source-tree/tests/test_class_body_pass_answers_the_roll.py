"""A class body's ``pass`` answers the roll with its block (#7757).

``ClassDef._class_body_block`` skips ``pass`` -- it runs nothing and binds
nothing -- and nothing answered for it (the board's ``Pass`` first
absentees after #8550: ``tests/extension/base/base.py:2:4``,
``tests/tslibs/test_array_to_datetime.py:293:4``,
``tests/frame/methods/test_reindex_like.py:37:12``).  It answers inert where
the body consumed it, as the class docstring does.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def test_a_class_body_pass_answers_the_roll():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write("class C:\n    pass\n")
    f.close()
    reporter = CollectingReporter()
    report = discharge(
        SourceFile(
            path_source(f.name),
            reporter=reporter,
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    assert ("Pass", 2, 4) in {
        (e.kind, e.start_line, e.start_col) for e in report.present
    }
    assert not [e for e in report.minority if e.kind == "Pass"]
