"""A ``with`` item and its ``as`` target answer with the ``with`` (#7757).

The ``with`` builds from its head (``With._construct_sugar``) and never
constructs its item as a value, so the item answered only where substitution
replaced it, and the ``as`` name it binds through (#8514's binding-spelling
rule, ``WithItem._bound_target_fields``) never answered: the binder that
spells it is never constructed (the board's ``Name`` first absentees at
``with ... as m``: ``tests/frame/test_arithmetic.py:51:34``,
``tests/io/excel/test_writers.py:132:39``).  The item is a structural part of
its statement (``WithItem._structural_part``) and answers, with its target,
where the ``with`` constructs.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import WithItem
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def test_a_with_item_is_a_structural_part():
    assert WithItem._structural_part


def test_a_with_as_name_answers():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(
        "class M:\n"
        "    def __enter__(self):\n"
        "        return 1\n"
        "\n"
        "    def __exit__(self, *exc):\n"
        "        return False\n"
        "\n"
        "\n"
        "def f():\n"
        "    with M() as m:\n"
        "        return m\n"
    )
    f.close()
    report = discharge(
        SourceFile(
            path_source(f.name),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert ("Name", 10, 16) not in absent
