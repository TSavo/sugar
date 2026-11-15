"""A bare annotated attribute's target answers the roll with its statement
(#7757).

``self.tr_row_num: int | None`` in a method (``io/formats/format.py:228``):
Python evaluates the receiver and discards it, never reading the attribute
and storing nothing (``AnnAssign._construct_sugar``).  Nothing constructs the
``Attribute`` target, which stayed on the roll: ``Attribute registered but
never answered the roll call`` on the pandas board at ``57ddf8b7d``.
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
    return discharge(
        SourceFile(
            path_source(f.name),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )


def test_the_bare_attribute_target_answers_with_its_statement():
    report = _report("def f(o):\n    o.x: int\n    return o\n")
    assert not any(
        e.kind == "Attribute" and e.start_line == 2 for e in report.minority
    ), report.minority
