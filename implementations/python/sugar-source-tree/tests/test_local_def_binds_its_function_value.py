"""A local plain ``def`` binds its name to the function value it builds (#7757).

Python's ``def`` statement builds a function and binds the name to it; a read
of the name is that value.  A local undecorated ``def`` bound its name to the
statement itself, so a join over it (``if p: def g(): ... else: g = None``)
built a phi whose arm was the whole function body: the board's
``IfExp.body/orelse is FunctionUniverseSugar`` refusal (14 files,
``core/algorithms.py:573``, ``core/_numba/extensions.py:448``).  It now binds
the function value under its evaluation key (``_binds_function_value``), as a
decorated ``def`` (#8593) and a ``class`` (#8501, #8520) do, and every read of
the name, a phi's arm included, reads that key.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _gaps(source: str):
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(source)
    f.close()
    reporter = CollectingReporter()
    discharge(
        SourceFile(
            path_source(f.name),
            reporter=reporter,
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    return [str(panic) for _node, panic in reporter.gaps]


def test_a_join_over_a_local_def_reads_its_value():
    gaps = _gaps(
        "def f(p):\n"
        "    if p:\n"
        "        def g():\n"
        "            return 1\n"
        "    else:\n"
        "        g = None\n"
        "    return g\n"
    )
    assert not [gap for gap in gaps if "FunctionUniverseSugar" in gap]
