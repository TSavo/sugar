"""An ``except`` clause answers the roll with its ``try`` (#7757).

``ExceptHandler`` is a grammar piece the ``try``'s construction consumes --
its matchers, its body and its slot (``Try._authenticated_handler_specs``)
-- and never constructs as a value of its own.  It had no construction and
nothing answered for it (the board's ``ExceptHandler`` first absentees after
#8550: ``__init__.py:12:4``, ``compat/numpy/__init__.py:39:4``,
``core/indexes/api.py:170:4``).  It is a structural part
(``_structural_part``) and answers where its ``try`` does, an arm no halt
reaches included.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import ExceptHandler
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def test_an_except_clause_is_a_structural_part():
    assert ExceptHandler._structural_part


def test_an_except_clause_answers_with_its_try():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(
        "def f(x):\n"
        "    try:\n"
        "        y = x + 1\n"
        "    except TypeError:\n"
        "        pass\n"
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
    present = {(e.kind, e.start_line, e.start_col) for e in report.present}
    assert ("ExceptHandler", 4, 4) in present
    assert not [e for e in report.minority if e.kind == "ExceptHandler"]
