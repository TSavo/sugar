"""A join's phi and an object state answer the roll where they are minted (#7757).

A ``try``'s or a live loop's join of a name builds a phi (``If._make_ifexp``,
its condition a ``BranchResultRef``), and ``x = f(...)`` refines the name's
binding to its object state (``Assign._object_place_state``:
``OpaqueObjectStateV1``, ``ObjectPlaceStateV1``).  Each is a binding, no source
node: where nothing reads the name after it (a module-level ``try``, a loop's
write after the loop, an object read only through a later state), nothing
constructs it, and it never answered (the board's first absentees
``core/_numba/kernels/shared.py:24:4`` ``BranchResultRef``,
``tests/indexes/datetimes/methods/test_isocalendar.py:26:4``
``OpaqueObjectStateV1``).  Each answers where it is minted.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile

_MINTED = ("IfExp", "BranchResultRef", "OpaqueObjectStateV1", "ObjectPlaceStateV1")


def _absent_minted(source: str):
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
    return [e for e in report.minority if e.kind in _MINTED]


def test_an_unread_try_join_answers():
    assert not _absent_minted(
        "try:\n    import json\n    ok = True\nexcept ImportError:\n    ok = False\n"
    )


def test_an_object_state_read_only_after_a_call_answers():
    assert not _absent_minted(
        "def f(g, h):\n"
        "    expected = tuple(g())\n"
        "    result = h.m()\n"
        "    return result == expected\n"
    )
