"""A parameter answers the roll when its definition answers (#7757).

A ``def``'s parameter is a grammar piece of the definition: the statement
evaluates its default (an ordinary child, which answers for itself) and binds
nothing of the parameter itself.  ``def __init__(self, data=None)`` in a
class body (``core/arrays/sparse/accessor.py:35:17``) left the ``Param``
registered and unanswered: the board's ``Param`` first absentees after #8349.
It is a structural part (``Param._structural_part``) and answers where its
definition answers present.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import Param
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def test_a_parameter_is_a_structural_part():
    assert Param._structural_part


def test_a_class_method_parameter_answers_the_roll():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write("class C:\n    def __init__(self, data=None):\n        self.d = data\n")
    f.close()
    reporter = CollectingReporter()
    report = discharge(
        SourceFile(
            path_source(f.name),
            reporter=reporter,
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    assert not [e for e in report.minority if e.kind == "Param"]
