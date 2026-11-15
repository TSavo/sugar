"""A read a substitution mints at a site and nothing builds answers where it is
minted (#7757).

``Call._cells_at_call`` asks the scope what each enclosing local a called
local ``def`` reads is bound to at the call.  Where the binding is guarded (one
arm of an ``if`` bound it), the read is a ``GuardedBindingRead`` minted at the
call's span, which the cell read refuses and nothing builds: it was registered
and never answered (``core/indexes/multi.py:3586`` ``_maybe_to_slice(loc)``,
``io/formats/console.py:75`` ``check_main()``).  The cell read is now the one
read of a scope at a site (``_name_read``), which answers such a read where it
is minted.
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


def test_a_guarded_cell_read_at_a_local_call_answers_where_minted():
    report = _report(
        "def f(c):\n"
        "    if c:\n"
        "        g = 1\n"
        "\n"
        "    def h():\n"
        "        return g\n"
        "\n"
        "    return h()\n"
    )
    assert not any(e.kind == "GuardedBindingRead" for e in report.minority), (
        report.minority
    )
