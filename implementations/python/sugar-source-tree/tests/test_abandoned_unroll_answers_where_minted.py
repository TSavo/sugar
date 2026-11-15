"""What an abandoned concrete unroll made answers the roll where it was made
(#7757).

A loop over a display whose body owns a ``break`` or ``continue`` under a
guard no ground value decides is not unrolled
(``For._unroll_concrete_controlled`` gives up at the guard) and stays a live
loop.  Each item's keyed store of its item (``<target> = <element>`` at the
loop's span, ``For._iteration_unpacks``) was made before the attempt and
built by nothing: ``Assign registered but never answered the roll call`` at
the ``for`` (``io/formats/style_render.py:2534``,
``tests/indexes/test_common.py:61``, six files on the pandas board at
``57ddf8b7d``).
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
def test_the_abandoned_items_answer_where_minted(jump):
    report = _report(
        "def f(s):\n"
        '    for x in ["a", "b"]:\n'
        "        if x in s:\n"
        f"            {jump}\n"
        "    return s\n"
    )
    assert not any(
        e.kind == "Assign" and e.start_line == 2 for e in report.minority
    ), report.minority
