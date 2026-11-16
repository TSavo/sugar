"""A comprehension over a ground list leaves nothing unanswered (#7757).

On the pandas board at ``d54a43717`` (run 43739300912) two files ended in
``Constant registered but never answered the roll call`` at a dict or set
comprehension over a name bound to a ground list
(``tests/groupby/test_timegrouper.py:528``, ``tests/io/test_stata.py:767``):
the dissolve minted an item read ``dates[i]`` with its index, gave up where
no ground value hashed the key, and nothing built what it minted.  The
dissolve is deleted (#8957): the comprehension is the one recurrence
(``ComprehensionSugar``) and mints no item node.  What stays owed is the
board's terminal: no ``Constant`` or ``Subscript`` of such a comprehension
is left unanswered.
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
    "source",
    [
        "def f(T, D):\n    dates = ['a', 'b']\n"
        "    return {T(d): D([d]) for d in dates}\n",
        "def f():\n    columns = ['tc', 'td']\n    return {c: c for c in columns}\n",
        "def f(T):\n    xs = [1, 2]\n    return {T(x) for x in xs}\n",
    ],
)
def test_no_constant_or_subscript_of_the_comprehension_is_left_unanswered(source):
    report = _report(source)
    assert not [
        e for e in report.minority if e.kind in {"Constant", "Subscript"}
    ], report.minority
