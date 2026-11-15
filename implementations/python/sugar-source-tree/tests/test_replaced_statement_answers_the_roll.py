"""A statement the block threading replaces answers the roll (#7757).

``xs.append(1)`` and ``d["k"] = 1`` on a list and a dict the block made
substitute to the one mutation door's statement, and a ``for`` over a
display dissolves into its iterations: nothing threaded in the source
statement's place is that occurrence, so nothing constructs it.  It
registered when the tree was materialized and nothing answered for it (the
board's ``Expr``, ``Assign``, ``For`` and ``AugAssign`` absentees after
#8349).  Its discharge is the substitution, as a replaced child's is, and so
is that of the names it bound through.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def test_a_statement_the_threading_replaced_answers_the_roll():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write('xs = []\nxs.append(1)\nd = {}\nd["k"] = 1\n')
    f.close()
    reporter = CollectingReporter()
    report = discharge(
        SourceFile(
            path_source(f.name),
            reporter=reporter,
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    assert reporter.gaps == []
    statements = {
        (e.kind, e.start_line, e.start_col)
        for e in report.present
        if e.kind in ("Assign", "Expr")
    }
    assert {("Expr", 2, 0), ("Assign", 4, 0)} <= statements
    assert not [e for e in report.minority if e.kind in ("Assign", "Expr")]
