"""Plan row 7 (step 6), part of #7799: a call keeps no raise as its value.

``CallSiteValue.project_producer_outcome`` projects a callee body's outcome
onto the Call node.  Its ``Complete`` arm asked only "is it one ``Complete``"
and seated the value as the call's retained completion.  A raise carried as
data, ``Complete(RaiseValue)``, became a completed ``CallSiteValue``: the
statement after the call ran, and the raise was gone.

The arm now goes through ``Complete.and_then``, the rule every expression
step already uses: an ordinary value is seated, a carried raise is handed
back unchanged, and the enclosing statement turns it into its halt the way
it does for ``1 // 0`` (``follow`` stops the block, ``promote_raise_halts``
makes the face).

No source shape found so far reaches this arm with a raise (the class body
of #7799 halts at the class statement since #7817, and before #7817 the
class completed with the raise stored as a field, so the call's outcome was
a completed object, not a raise), and no pandas corpus file reaches it.
The twin below therefore puts the raise there directly: the callee body's
outcome is replaced by the ground ``ZeroDivisionError`` exit, the exact
value ``1 // 0`` produces.

Before this change ``a = f()`` and ``return f()`` completed with the raise
dropped.  ``f()`` as a statement already halted: the statement reads the
retained body back (``retained_source_completion_outcome().and_then``),
which hands the raise on.
"""

from __future__ import annotations

import pytest

_CALLEE = "def f():\n    return 1\n\n\n"

_USES = {
    "assign-unread": "    a = f()\n    return 3\n",
    "bare-call": "    f()\n    return 3\n",
    "assign-and-return": "    a = f()\n    return a\n",
    "return-the-call": "    return f()\n",
}


def _tree(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.tree import SourceFile

    return SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _function(source: str, name: str = "test_f"):
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree import nodes

    tree = _tree(source)
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, nodes.FunctionDef) and node.name == name
    )
    return function_universe_outcome(function)


def _faces(outcome) -> tuple[int, tuple[str, ...]]:
    """(completed faces, the effect of each halted face) of an outcome."""
    from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted

    if isinstance(outcome, Complete):
        assert outcome.follow().continues, outcome
        return 1, ()
    assert isinstance(outcome, ExitSet), outcome
    return (
        sum(isinstance(face, Completed) for face in outcome.exits),
        tuple(repr(face.effect) for face in outcome.exits if isinstance(face, Halted)),
    )


@pytest.fixture
def callee_raises(monkeypatch):
    """The callee body's outcome is ``Complete(RaiseValue)``: ``1 // 0``."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

    def reduce_source_outcome(self, ctx=None):
        del ctx
        return ground_exceptional_exit(
            exception_name="ZeroDivisionError", site=self.site, owner="BinOp"
        )

    monkeypatch.setattr(CallSiteValue, "reduce_source_outcome", reduce_source_outcome)


# ---------------------------------------------------------------------------
# The twin at the reduction level.  One thing differs: the callee's outcome.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("use", sorted(_USES))
def test_a_call_whose_callee_completes_completes(use: str) -> None:
    completed, halts = _faces(_function(_CALLEE + "def test_f():\n" + _USES[use]))

    assert (completed, halts) == (1, ())


@pytest.mark.parametrize("use", sorted(_USES))
def test_a_call_whose_callee_carries_a_raise_halts_with_it(
    use: str, callee_raises
) -> None:
    completed, halts = _faces(_function(_CALLEE + "def test_f():\n" + _USES[use]))

    assert completed == 0
    assert len(halts) == 1 and "ZeroDivisionError" in halts[0]


def test_the_general_form_is_unchanged() -> None:
    """``def f(): raise ValueError``: the callee body is already a halted face
    when it reaches the call, and each use is one halt, as before."""
    for use in _USES.values():
        completed, halts = _faces(
            _function("def f():\n    raise ValueError\n\n\ndef test_f():\n" + use)
        )

        assert completed == 0
        assert len(halts) == 1 and "ValueError" in halts[0]


# ---------------------------------------------------------------------------
# The projection itself.
# ---------------------------------------------------------------------------


@pytest.fixture
def callsite(monkeypatch):
    """The ``f()`` call site of ``a = f()``, as the reduction constructs it."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

    seen = []
    project = CallSiteValue.project_producer_outcome

    def spy(self, outcome, **kwargs):
        seen.append(self)
        return project(self, outcome, **kwargs)

    monkeypatch.setattr(CallSiteValue, "project_producer_outcome", spy)
    _function(_CALLEE + "def test_f():\n    a = f()\n    return 3\n")
    monkeypatch.setattr(CallSiteValue, "project_producer_outcome", project)
    (site,) = seen
    return site


def test_the_projection_seats_an_ordinary_value(callsite) -> None:
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.outcome import Complete

    projected = callsite.project_producer_outcome(Complete(TermValue(1)))

    assert isinstance(projected, Complete)
    assert isinstance(projected.value, CallSiteValue)
    assert projected.value.retained_source_completion_outcome() == Complete(
        TermValue(1)
    )


def test_the_projection_hands_a_carried_raise_back_unchanged(callsite) -> None:
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
    from sugar_lift_py_tests.outcome import Complete

    raised = ground_exceptional_exit(
        exception_name="ZeroDivisionError", site=callsite.site, owner="BinOp"
    )
    assert isinstance(raised, Complete)

    projected = callsite.project_producer_outcome(raised)

    assert projected == raised
    assert not projected.follow().continues
