"""A lowered delete's receiver and index answer the roll by their substitution
(#7757).

A ``del`` the one door does not take (``del k[-1], v[-1]``, ``del o.a``,
``del stack[:], stack``) is lowered to its delete operations, each built from
its target's receiver (and index) substituted where the statement runs.  The
lowering called ``substitute`` on those parts directly, so a read the rewrite
replaced -- a formal's ``FormalRef``, a local's reference to its evaluation --
was answered by nothing: on the pandas board at ``d54a43717`` (run
43739300912) three files ended in ``Name registered but never answered the
roll call`` at the receiver (``core/_numba/extensions.py:64`` ``del
index._numba_data``, ``tests/config/test_config.py:364`` ``del k[-1],
v[-1]``, ``core/computation/scope.py:313`` ``del stack[:], stack``).  Each
part now substitutes as the one door's does (``_substitute_field``): the
replaced read answers by that substitution, and what replaced it answers
where the operation builds it.
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
        "def f(k, v):\n    del k[-1], v[-1]\n",
        "def f(index):\n    del index._numba_data\n",
        "def f(o):\n    del o.a, o.b\n",
        "def f(xs):\n    stack = list(xs)\n    del stack[:], stack\n",
    ],
)
def test_the_lowered_delete_leaves_nothing_unanswered(source):
    report = _report(source)
    last = source.count("\n")
    assert not [e for e in report.minority if e.start_line == last], report.minority
