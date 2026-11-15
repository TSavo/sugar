"""An import alias answers the roll where its statement constructs (#7757).

``from __future__ import annotations`` constructs ``InertSugar``: the
statement binds ``annotations`` through its alias and constructs nothing of
it.  The alias registered on the roll when the tree was materialized and
nothing answered for it, so every pandas file with an import had a silent
absentee (the board's ``UnaccountedConstruction`` after #8349).  The
statement answers for each alias by the one discharge of a node a
construction absorbs without constructing it.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def test_every_import_alias_answers_where_its_statement_constructs():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write("from __future__ import annotations\nimport os\nimport os.path as p\n")
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
    aliases = {
        (e.start_line, e.start_col) for e in report.present if e.kind == "ImportAlias"
    }
    assert aliases == {(1, 23), (2, 7), (3, 7)}
    assert not [e for e in report.minority if e.kind == "ImportAlias"]
