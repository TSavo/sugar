"""A structural part answers the roll when its parent constructs (#7757).

A call's keyword, a dict display's item and a comprehension's clause are
grammar pieces their parent's construction consumes: ``Call`` reads
``keyword.value.sugar()``, a display its items' keys and values, a
comprehension its clauses' iterables and conditions.  None of them is
constructed as a value, so each registered when the tree was materialized and
nothing answered for it (the board's ``Keyword``, ``DictItem`` and
``Comprehension`` first absentees after #8349).  It answers where its parent
constructed (``Node.structural_parts``); what it holds that Python evaluates
answers for itself.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import Comprehension, DictItem, Keyword, Node
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile

_PARTS = ("Keyword", "DictItem", "Comprehension")


def test_structural_parts_are_declared_on_their_class():
    assert Keyword._structural_part
    assert DictItem._structural_part
    assert Comprehension._structural_part
    assert not Node._structural_part


def test_a_structural_part_answers_when_its_parent_constructs():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(
        "ys = sorted((2, 1), reverse=True)\n"
        'd = {"k": 1}\n'
        "zs = [x for x in (1, 2) if x]\n"
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
    present = {e.kind for e in report.present if e.kind in _PARTS}
    assert present == set(_PARTS)
    assert not [e for e in report.minority if e.kind in _PARTS]
