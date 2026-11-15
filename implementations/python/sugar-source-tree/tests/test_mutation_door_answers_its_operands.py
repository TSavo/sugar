"""Every operand the one mutation door evaluates answers the roll (#7757).

``r += x`` is the door's in-place call on the object ``r`` denotes
(``container_mutation.name_mutation_statement``).  Its operand ``x`` was
substituted apart from its statement (``self.value.substitute``), so a source
read the rewrite replaced -- ``values += data``'s ``data`` (a reference) at
``core/frame.py:2372`` -- or a comprehension it dissolved -- ``names += ["W-" +
day for day in days]`` at ``tests/tseries/offsets/test_offsets.py:918`` --
answered nothing: built by nothing, discharged by nothing.  It substitutes as
every other operand of the door does (``_substitute_field``), and the
replaced source node answers by that substitution.
"""

import tempfile

import pytest

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


@pytest.mark.parametrize(
    ("statement", "kind", "operand"),
    [
        ("values += data", "Name", "data"),
        ('values += ["W-" + d for d in ("a", "b")]', "ListComp", "["),
    ],
)
def test_an_inplace_operand_answers_the_roll(statement, kind, operand):
    report = _report(
        f"def f(data):\n    values = [1]\n    {statement}\n    return values\n"
    )
    column = 4 + statement.index(operand)
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert (kind, 3, column) not in absent
