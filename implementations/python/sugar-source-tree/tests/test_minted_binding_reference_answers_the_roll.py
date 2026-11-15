"""A binding the rewrite mints answers the roll where it is minted (#7757).

A formal's ``FormalRef`` (and a frame's ``BindingCoordinateRef``) at its
parameter, a walrus's or a comprehension member's ``EvaluationRef`` at its
target, and the ``ReceiverAfterCall`` a call leaves for an object it may
have changed are values of a scope, never source occurrences: a read is
re-spanned to its own site and answers for itself.  One no read reaches was
constructed by nothing (the board's ``FormalRef`` / ``BindingCoordinateRef``
/ ``ReceiverAfterCall`` first absentees after #8349:
``tests/groupby/__init__.py:1:28``, ``tests/arrays/floating/test_repr.py:22:20``,
``tests/copy_view/util.py:30:4``).  It answers where it is minted
(``_minted_binding_reference``).
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile

_MINTED = ("FormalRef", "BindingCoordinateRef", "EvaluationRef", "ReceiverAfterCall")


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


def test_an_unread_formal_answers_where_it_is_minted():
    report = _report(
        "def f(name, obj):\n"
        "    return name\n"
        "\n"
        "\n"
        "class TestBox:\n"
        "    def test_one(self):\n"
        "        assert 1\n"
    )
    assert not [e for e in report.minority if e.kind in _MINTED]


def test_an_unread_member_and_walrus_answer_where_they_are_minted():
    report = _report(
        "def f(xs):\n"
        "    if (m := len(xs)):\n"
        "        return [1 for _ in xs]\n"
        "    return []\n"
    )
    assert not [e for e in report.minority if e.kind in _MINTED]
