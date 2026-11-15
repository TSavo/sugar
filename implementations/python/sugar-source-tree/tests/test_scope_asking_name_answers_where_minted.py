"""A name read minted to ask the scope answers the roll where it is minted (#7757).

``_name_read`` mints a ``Name`` at a def's or a statement's span to read a
shared object as the frame leaves it (``_exit_reads``,
``_ExitReadFrameV1.leaving``) or a receiver as an initializer holds it, and a
comprehension mints one per walrus to read the name's prior binding
(``ListComp._carrying_walrus_priors``).  Substitution replaces the minted read
by the binding, or it is dropped where nothing is bound, so nothing
constructs it: it never answered (the board's first absentees
``tests/api/test_types.py:55:4`` and ``tests/frame/methods/test_dot.py:42:4``,
a ``Name`` at a method's span; ``tests/tseries/offsets/test_dst.py:39:0``).
Each answers where it is minted, as the cell read at a call already does
(``Call._cells_at_call``).
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _absent_names(source: str):
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
    return [e for e in report.minority if e.kind == "Name"]


def test_a_followed_helper_changing_its_formal_answers_its_exit_read():
    assert not _absent_names(
        "def g(xs):\n"
        "    xs.append(1)\n"
        "    return xs\n"
        "\n"
        "def f():\n"
        "    ys = []\n"
        "    g(ys)\n"
        "    return ys\n"
    )


def test_a_comprehension_walrus_prior_answers():
    assert not _absent_names(
        "def f(xs):\n"
        "    last = None\n"
        "    ys = [(last := x) for x in xs]\n"
        "    return last, ys\n"
    )
