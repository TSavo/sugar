"""A module is run once per session in the normal flow (#7757, after #8073).

The module's reduction (``tree_enumerate.owner_reduction`` with no owner)
marks its own run under way (``_MODULE_RUNS_UNDER_WAY``): that mark is the
reduction row's own act, never an input it read.  So a run computed inside
``module_end_contexts`` is the row a later top-level ``owner_reduction(None)``
is served, and the module body is not run again.

The cycle rule #8050 needed still holds: an answer computed while ANOTHER
module's run was under way is served only where that run is under way again.
"""

from __future__ import annotations

from types import SimpleNamespace


def _module(body):
    """A unit whose module body is ``body()``, returning ``(outcome, ends)``."""
    span = SimpleNamespace(start_line=1, start_col=0, end_line=9, end_col=0)
    unit = SimpleNamespace()
    root = SimpleNamespace(
        unit=unit,
        kind="Module",
        reporter=object(),
        line_col_span=lambda: span,
        sugar=lambda: SimpleNamespace(run=lambda _context: body()),
    )
    unit.constructed_module = SimpleNamespace(root=root)
    return unit


def _fresh(monkeypatch, tree_enumerate) -> None:
    monkeypatch.setattr(tree_enumerate, "_OWNER_REDUCTIONS", {})
    monkeypatch.setattr(tree_enumerate, "_MODULE_RUNS", {})
    monkeypatch.setattr(tree_enumerate, "_MODULE_RUN_UNITS", {})


def test_module_end_contexts_then_owner_reduction_runs_the_module_once(
    monkeypatch,
) -> None:
    from sugar_lift_py_tests import tree_enumerate

    _fresh(monkeypatch, tree_enumerate)
    runs: list = []

    def body():
        # The body reads its own run's mark: a read of its own final
        # binding while it runs.
        runs.append(tree_enumerate.module_end_contexts(unit))
        return "outcome", ("end",)

    unit = _module(body)

    assert tree_enumerate.module_end_contexts(unit) == ("end",)
    reduction = tree_enumerate.owner_reduction(None, unit.constructed_module)
    assert reduction.ends == ("end",)
    assert tree_enumerate.module_end_contexts(unit) == ("end",)
    assert runs == [()]


def test_owner_reduction_then_module_end_contexts_runs_the_module_once(
    monkeypatch,
) -> None:
    from sugar_lift_py_tests import tree_enumerate

    _fresh(monkeypatch, tree_enumerate)
    runs: list = []

    def body():
        runs.append(tree_enumerate.module_end_contexts(unit))
        return "outcome", ("end",)

    unit = _module(body)

    reduction = tree_enumerate.owner_reduction(None, unit.constructed_module)
    assert reduction.ends == ("end",)
    assert tree_enumerate.module_end_contexts(unit) == ("end",)
    assert tree_enumerate.owner_reduction(None, unit.constructed_module) is reduction
    # The top-level reduction is the run under way: its own read of itself
    # is empty, and it never runs itself again inside itself.
    assert runs == [()]


def test_an_answer_computed_under_another_modules_run_is_recomputed_outside_it(
    monkeypatch,
) -> None:
    from sugar_lift_py_tests import tree_enumerate

    _fresh(monkeypatch, tree_enumerate)
    a_runs: list = []
    b_runs: list = []

    def a_body():
        a_runs.append(tree_enumerate.module_end_contexts(b))
        return "outcome", ("a-end",)

    def b_body():
        seen = tree_enumerate.module_end_contexts(a)
        b_runs.append(seen)
        return "outcome", ("b-end", seen)

    a = _module(a_body)
    b = _module(b_body)

    # A's run reaches B's run, which reads A while A is under way: empty.
    assert tree_enumerate.module_end_contexts(a) == ("a-end",)
    assert a_runs == [("b-end", ())]
    assert b_runs == [()]

    # Outside A's run, B's answer computed under it is not served: B runs
    # again and reads A's completed run.
    assert tree_enumerate.module_end_contexts(b) == ("b-end", ("a-end",))
    assert b_runs == [(), ("a-end",)]

    # Each answer is now served where its reads hold: no module runs again.
    a_count, b_count = len(a_runs), len(b_runs)
    assert tree_enumerate.module_end_contexts(b) == ("b-end", ("a-end",))
    assert tree_enumerate.owner_reduction(None, b.constructed_module).ends == (
        "b-end",
        ("a-end",),
    )
    assert tree_enumerate.module_end_contexts(a) == ("a-end",)
    assert tree_enumerate.owner_reduction(None, a.constructed_module).ends == (
        "a-end",
    )
    assert (len(a_runs), len(b_runs)) == (a_count, b_count)
