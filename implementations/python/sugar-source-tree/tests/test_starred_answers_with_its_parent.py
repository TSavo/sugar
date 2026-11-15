"""``*e`` answers the roll with the display or call that unpacks it (#7757).

A list, tuple or set display with a starred member unpacks it
(``SpreadCollectionSugar``: ``("python:starred", e.value.sugar())``), and a
call spreads it (``SpreadCallSugar``); neither constructs the ``Starred`` node,
so it never answered (the board's ``Starred`` first absentees:
``util/__init__.py:29:12`` ``[*list(globals().keys()), ...]``,
``core/indexes/period.py:83:43``).  It is a structural part of its parent
(``Starred._structural_part``); ``e`` answers for itself.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import Starred
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def test_a_starred_member_is_a_structural_part():
    assert Starred._structural_part


def test_a_starred_display_member_answers():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write("def f(xs):\n    return [*xs, 1]\n")
    f.close()
    report = discharge(
        SourceFile(
            path_source(f.name),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert ("Starred", 2, 12) not in absent
