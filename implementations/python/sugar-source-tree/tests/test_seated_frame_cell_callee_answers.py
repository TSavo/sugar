"""A seated call whose callee is a frame's read of a captured cell answers
that read (#7757).

In a frame's body a call of the enclosing function's local ``def`` spells its
callee through the frame's read of the captured cell (a
``BindingCoordinateRef`` re-spanned to the callee, ``Name.substitute``).  The
call's lexical row seats that definition's frame by its name
(``Call._construct_sugar``) and the call-site coordinate absorbs the callee,
which never constructs: the read stayed on the roll unanswered.  On the
pandas board at ``d54a43717`` (run 43739300912) six files ended so: ``return
_check(inst)`` (``core/dtypes/generic.py:45``), ``return
base_formatter(v)...`` (``io/formats/format.py:1329``), ``return
freduce(x)``, ``float_result_type(dtype, dtype2)``, ``lambda x:
check_row_subclass(x)``, ``lambda x: noddy(...)``.  The absorbed read now
answers, as an absorbed Name callee does.
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
        "def outer(xs):\n    def freduce(g):\n        return g\n"
        "    def freducex(x):\n        return freduce(x)\n"
        "    return freducex(xs)\n",
        "def outer(apply):\n    def check(x):\n        return x\n"
        "    return apply(lambda x: check(x))\n",
    ],
)
def test_the_absorbed_cell_callee_answers(source):
    report = _report(source)
    assert not [
        e for e in report.minority if e.kind in {"BindingCoordinateRef", "Name"}
    ], report.minority
