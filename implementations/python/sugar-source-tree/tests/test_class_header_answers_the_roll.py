"""A class statement builds every expression of its header (#7757).

Python evaluates a ``class`` statement's bases and its keyword values
(``metaclass=ABCMeta``) where the statement runs, before the body.  The
keyword values were built by nothing (``core/arrays/arrow/accessors.py:33:30``
``ABCMeta``), and a local base unwrapped to its class's read left the base's
own name unanswered.  The statement now evaluates each keyword value after
the bases (``ClassDefinitionSugar.keyword_sugars``), and a local base's
name answers by the read that replaced it.
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


def test_a_class_keyword_value_answers_by_construction():
    report = _report(
        "from abc import ABCMeta\n\n\nclass C(metaclass=ABCMeta):\n    pass\n"
    )
    assert not [e for e in report.minority if e.start_line == 4]


def test_a_local_base_answers_by_its_read():
    report = _report("class Base:\n    pass\n\n\nclass Box(Base):\n    pass\n")
    assert not [e for e in report.minority if e.start_line == 5]
