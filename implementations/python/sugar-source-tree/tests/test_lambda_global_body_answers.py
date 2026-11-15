"""A lambda whose body is the bare read of a module global answers the roll
for that read (#7757).

``Lambda._construct_sugar`` substitutes its body with the module's binding of
each global it reads (``_module_global_references``).  A body that is the
read itself (``lambda x: lorem_ipsum``) was replaced by its reference with
nothing to answer for the replaced ``Name``: a read inside a larger body is
replaced by its parent's substitution, which answers for it.
``tests/io/formats/test_to_html.py:782`` ended in ``Name registered but never
answered the roll call`` on the pandas board at ``d54a43717`` (run
43739300912).  The body goes through the one field door
(``_substitute_field``), which answers for what it replaces.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def test_a_lambda_reading_a_global_as_its_body_leaves_no_absentee():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(
        "TEXT = 'abc'\n"
        "CASES = [lambda x: TEXT, lambda x: TEXT[:x]]\n"
        "def f(n):\n"
        "    return [case(n) for case in CASES]\n"
    )
    f.close()
    report = discharge(
        SourceFile(
            path_source(f.name),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    assert not [
        e for e in report.minority if e.kind == "Name" and e.start_line == 2
    ], report.minority
