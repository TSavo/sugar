"""An item store's or a delete's target answers the roll with the operation it
is the site of (#7757).

A store on a receiver no bound name reaches through a path (``self.iloc[i] =
v`` on a formal, ``f(x)[k] = v``) is the ordinary store
(``_valued_store_target_sugar``): it builds the receiver and the index and
makes the one ``__setitem__`` the target stands for.  A ``del`` the one door
does not take (``del os.environ["TZ"]``, ``del k[-1], v[-1]``) is lowered to
its delete operations.  Neither constructed the target, which stayed on the
roll unanswered: 47 files on the pandas board at ``57ddf8b7d`` ended in
``Subscript registered but never answered the roll call``
(``core/frame.py:4693``, ``tests/config/test_config.py:364``).  Each target
now answers by that absorption, as the container-mutation door's item store
does (``container_mutation._container_call``).
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
        "def f(o, v):\n    o.a[0] = v\n",
        "def f(g, v):\n    g()[0] = v\n",
        "def f(k, v):\n    del k[-1], v[-1]\n",
        "def f(o):\n    del o.a[0]\n",
    ],
)
def test_the_target_answers_with_its_operation(source):
    report = _report(source)
    assert not any(
        e.kind == "Subscript" and e.start_line == 2 for e in report.minority
    ), report.minority
