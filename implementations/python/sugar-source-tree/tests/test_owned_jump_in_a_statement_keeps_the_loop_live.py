"""A ``break`` or ``continue`` a concrete loop owns inside a statement no
ground guard selects keeps the loop live (#7757).

``for j in range(5): try: chunk = it.read() except StopIteration: break``
(``tests/io/test_stata.py:1313``): the controlled unroll
(``For._substitute_controlled_suite``) selects a jump only under an ``if``
whose guard is ground, or a ``try`` whose body is the jump alone.  It
linearized any other statement holding one, and the jump was left with no
enclosing loop: its construction raised ``loop-control occurrence has no
enclosing loop`` and the file failed the board's instrument.  The unroll now
gives up there and the loop is built live.
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


@pytest.mark.parametrize("jump", ["break", "continue"])
def test_a_jump_in_a_handler_is_routed_by_the_live_loop(jump):
    report = _report(
        "def f(it):\n"
        "    for j in range(2):\n"
        "        try:\n"
        "            chunk = it.read()\n"
        "        except StopIteration:\n"
        f"            {jump}\n"
        "    return it\n"
    )
    assert not any(e.kind in ("Break", "Continue") for e in report.minority), (
        report.minority
    )
