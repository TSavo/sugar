"""An unpack's member read answers the roll where it is minted (#7757).

``a, b = f(x)`` binds each name to a reference to its projection of the
statement's one evaluation, carrying as ``of`` the object the unpack gives it:
the item read ``f(x)[0]`` (``For._item_of``) or, for a starred name, the slice
read (``For._slice_of``), minted at the statement's span with a minted index
(``For._int_constant``).  Python evaluates no subscript there; the read only
names which object the name denotes, and nothing built it, so it never
answered (the board's first absentees ``core/arrays/boolean.py:400:12``
``Constant`` and ``Subscript``, ``core/arrays/numeric.py:100:8``).  Each
answers where it is minted.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _absent(source: str):
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
    return [e for e in report.minority if e.kind in ("Constant", "Subscript", "Slice")]


def test_a_call_unpack_answers_its_member_reads():
    assert not _absent(
        "def f(g, other):\n"
        "    other, mask = g(other, copy=False)\n"
        "    return other, mask\n"
    )


def test_a_starred_unpack_answers_its_slice_read():
    assert not _absent(
        "def f(g):\n"
        "    first, *rest, last = g()\n"
        "    return first, rest, last\n"
    )


def test_a_nested_unpack_answers_every_level():
    assert not _absent(
        "def f(case):\n"
        "    offset, (base, expected) = case\n"
        "    return offset, base, expected\n"
    )
