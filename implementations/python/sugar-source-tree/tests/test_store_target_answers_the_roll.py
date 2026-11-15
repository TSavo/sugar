"""A store's target answers the roll by the store that absorbs it (#7757).

``o.x = v`` substitutes to the one field store
(``ReceiverFieldStoreStatement``) and ``r[k] = v`` to the one door's
``__setitem__`` (``PathContainerCall``): each builds the receiver and the
operands and makes the one store the target stands for, so the source
``Attribute`` / ``Subscript`` target is constructed by nothing.  Nothing
answered for it (the board's ``Attribute`` and ``Subscript`` first absentees
after #8550: ``core/arrays/sparse/accessor.py:36:8`` ``self._parent``,
``core/arrays/boolean.py:212:8`` ``values_bool[~mask_values]``,
``io/excel/_util.py:47:4`` ``_writers[engine_name]``), and neither did a
receiver read the rewrite replaced (``self`` re-spanned to its formal), since
the store substituted it directly.  The store's absorption is the target's
discharge, and each part substitutes as every store target's does.
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
    reporter = CollectingReporter()
    return discharge(
        SourceFile(
            path_source(f.name),
            reporter=reporter,
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )


def _present(report) -> set:
    return {(e.kind, e.start_line, e.start_col) for e in report.present}


def test_a_field_store_target_and_its_receiver_answer_by_the_store():
    report = _report(
        "class Box:\n"
        "    def __init__(self, data):\n"
        "        self._parent = data\n"
    )
    present = _present(report)
    assert ("Attribute", 3, 8) in present
    assert ("Name", 3, 8) in present


def test_an_item_store_target_answers_by_the_store():
    report = _report("def f(k, v):\n    d = {}\n    d[k] = v\n    return d\n")
    present = _present(report)
    assert ("Subscript", 3, 4) in present
    assert ("Name", 3, 4) in present
