"""The read of a module global the module body does not decide answers the
roll where it is minted (#7757).

Since #8802 a reader of such a global (a ``def``, a lambda, a class body)
reads it through its undecided key (``undecided_module_binding_key``): the
reference is minted at the reader's span and each read of the name is
re-spanned to its own site (``Name.substitute``), which answers for itself.
The minted reference is built by nothing, so it answers where it is minted
(``_minted_binding_reference``); otherwise every file #8802 stopped refusing
would end in ``EvaluationRef registered but never answered the roll call`` at
the reader.
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


def test_an_undecided_global_read_answers_where_minted():
    # ``add()`` may change the list ``X`` names, so ``f`` (line 5) reads ``X``
    # through its undecided key.
    report = _report(
        "X = []\n"
        "def add():\n"
        "    X.append(1)\n"
        "add()\n"
        "def f():\n"
        "    return X\n"
    )
    assert not any(
        e.kind == "EvaluationRef" and e.start_line == 5 for e in report.minority
    ), report.minority
