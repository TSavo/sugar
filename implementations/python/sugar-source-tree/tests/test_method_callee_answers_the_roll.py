"""A method call's callee answers the roll by the call (#7757).

``o.m(...)`` constructs ``MethodCallSugar``: the receiver ``o`` is built and
``m`` is read through the one attribute lookup the call makes, so the callee
``Attribute`` constructs nothing of its own.  Where the substitution left
the callee as it stands (a receiver no binding rewrites: ``super()``, a set
display, a module global), nothing answered for it -- the board's largest
first-absentee kind after #8550 (``core/computation/pytables.py:66:8``
``super().__init__``, ``core/arraylike.py:312:34`` ``{DataFrame,
Series}.issubset``, ``core/arrays/string_arrow.py:77:40``
``pa.types.is_string_view``).  The call's absorption of it is its discharge.
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
    reporter = CollectingReporter()
    return discharge(
        SourceFile(
            path_source(f.name),
            reporter=reporter,
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )


def test_a_method_callee_the_substitution_left_answers_by_the_call():
    report = _report("def f(xs):\n    return {1, 2}.issubset(xs)\n")
    assert ("Attribute", 2, 11) in {
        (e.kind, e.start_line, e.start_col) for e in report.present
    }
    assert not [e for e in report.minority if e.kind == "Attribute"]
