"""An import member's receiver answers the roll with the member read (#7757).

``np.add`` under ``import numpy as np`` reads the member through its
authenticated receipt (``ImportMemberSugar``): the receiver ``np`` is the
import's spelling, absorbed into the read's coordinate, and was never built
nor answered (the board's ``Name`` first absentees after #8349:
``tests/arrays/boolean/test_function.py:9:14``,
``compat/numpy/__init__.py:10:14``).  Every node of the receiver chain answers
present-inert, as an import-bound callee's does.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def test_an_import_member_receiver_answers_the_roll():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write("import re\n\nE = re.error\nF = [re.error, re.escape]\n")
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
        e for e in report.minority if e.kind == "Name" and e.start_line in (3, 4)
    ]
