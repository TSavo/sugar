"""The store a ``with ... as <name>:`` mints to read its binding answers the
roll where it is minted (#7757).

``With.substitution_binding`` reads the ``as`` name's binding through the one
assignment seam: it mints ``<name> = ObservationRef(enter slot)`` at the
``with``'s span and asks that ``Assign`` for its binding.  The store is no
statement of any block and nothing constructs it, so it stayed registered and
never answered: every file with a ``with ... as <name>:`` ended in
``Assign registered but never answered the roll call`` at the ``with``
(``_testing/_warnings.py:101``, ``io/formats/csvs.py:251``, 77 files on the
board at ``57ddf8b7d``).
"""

import tempfile

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


def test_the_with_as_store_answers_where_minted():
    report = _report(
        "def f(p):\n"
        "    with open(p) as handle:\n"
        "        data = handle.read()\n"
        "    return data\n"
    )
    assert not any(
        e.kind == "Assign" and e.start_line == 2 for e in report.minority
    ), report.minority

