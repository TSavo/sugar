"""An assignment target's reference answers the roll where it is minted (#7757).

``y = e`` binds ``y`` to its projection of the statement's evaluation
(``_keyed_target_binding``), and ``x = m.f(...)`` through the one mutation
door binds ``x`` to the call's value under its key
(``container_mutation._name_write``).  Each reference is a binding: a read of
the name is re-spanned to its own site and answers for itself, so nothing
constructs the reference at the target's span.  The mutation statement holds
it in ``states`` but builds only ``evaluated``, so the block threading's
discharge read it as a node the statement constructs and never answered it
(the board's ``EvaluationRef`` first absentees at assignment targets:
``core/array_algos/quantile.py:94:8`` ``flat = np.full(...)``,
``tests/arrays/floating/test_repr.py:33:4`` ``data = pd.array(...)``).
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


def test_a_mutation_door_target_reference_answers():
    report = _report(
        "import numpy as np\n"
        "\n"
        "\n"
        "def f(qs, fill_value):\n"
        "    flat = np.full(len(qs), fill_value)\n"
        "    return repr(flat)\n"
    )
    assert not [
        e
        for e in report.minority
        if e.kind == "EvaluationRef" and (e.start_line, e.start_col) == (5, 4)
    ]


def test_an_assignment_target_reference_answers():
    report = _report(
        "def f(a):\n"
        "    data = [a, 1]\n"
        "    result = repr(data)\n"
        "    return result\n"
    )
    assert not [
        e
        for e in report.minority
        if e.kind == "EvaluationRef" and e.start_line in (2, 3) and e.start_col == 4
    ]
