"""An annotated store's recast statements answer the roll (#7757).

``o.f: T = v`` is the store ``o.f = v`` (``AnnAssign._store_assignment``, an
``Assign`` recast over the same occurrence), and in a module body its
annotation is the expression statement after it
(``AnnAssign._annotation_statement``, an ``Expr`` recast the same way).
Substitution replaces the recast ``Assign`` by the one store door (the
receiver field store), so nothing constructed it and it never answered (the
board's first absentees ``io/formats/csvs.py:85:8``
``self.compression: CompressionOptions = compression``,
``io/formats/info.py:289:8``).  Each recast a substitution replaces answers
where it is substituted.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _absent_statements(source: str):
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(source)
    f.close()
    report = discharge(
        SourceFile(
            path_source(f.name),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    return [e for e in report.minority if e.kind in ("Assign", "Expr")]


def test_an_annotated_field_store_in_an_initializer_answers():
    assert not _absent_statements(
        "class C:\n"
        "    def __init__(self, data):\n"
        "        self.data: list = data\n"
    )


def test_an_annotated_item_store_in_a_function_answers():
    assert not _absent_statements(
        "def f(d, v):\n"
        "    d['k']: int = v\n"
        "    return d\n"
    )
