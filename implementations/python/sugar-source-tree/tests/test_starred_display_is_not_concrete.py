"""A display with a ``*xs`` member is no concrete iterable (#7757).

``[self, *dtypes]`` has one item per item of ``dtypes`` besides ``self``.
``For._concrete_elements`` took the display's members as its items, so the
comprehension ``[cast(D, t).base for t in [self, *dtypes]]`` dissolved into
two members, the second ``cast(D, *dtypes).base``, and the iterable's
``self`` read, bound to the target and re-spanned to its read, was built by
nothing: ``core/dtypes/dtypes.py:974`` ended in ``FormalRef registered but
never answered the roll call`` on the pandas board at ``d54a43717`` (run
43739300912).  The display decides how many items there are only where each
member is one item; otherwise the loop or comprehension stays live.

Since #7757 new 6 no display is unrolled at the rewrite: every comprehension
is reduced by its own fold, so what is left to check is that nothing is left
unanswered.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile

_SOURCE = (
    "def f(first, *rest):\n"
    "    return [len(t) for t in [first, *rest]]\n"
)


def _tree(source: str, reporter=None) -> SourceFile:
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(source)
    f.close()
    kwargs = {} if reporter is None else {"reporter": reporter}
    return SourceFile(
        path_source(f.name),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        **kwargs,
    )


def test_a_comprehension_over_a_starred_display_leaves_no_absentee():
    report = discharge(_tree(_SOURCE, CollectingReporter()))
    assert not [
        e
        for e in report.minority
        if e.kind in ("FormalRef", "BindingCoordinateRef") and e.start_line == 2
    ], report.minority
