"""Plan row 7 (step 6), part of #7799: a call keeps no raise as its value.

``CallSiteValue.project_producer_outcome`` projects a callee body's outcome
onto the Call node.  Its completed arm asked only "is it one completed value"
and seated the value as the call's retained completion.  A raise carried as
data (a completed ``RaiseValue``, removed by #7821), became a completed ``CallSiteValue``: the
statement after the call ran, and the raise was gone.

The arm now goes through ``and_then``, the rule every expression
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
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    value = outcome.completed_value()
    if value is not None:
        assert value.follow_rest().continues, outcome
        return 1, ()
    return (
        sum(isinstance(face, Completed) for face in outcome.exits),
        tuple(repr(face.effect) for face in outcome.exits if isinstance(face, Halted)),
    )


@pytest.fixture
def callee_raises(monkeypatch):
    """The callee body's outcome is the ground ``1 // 0`` halt."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

    def _reduce_source_outcome(self, ctx=None):
        del ctx
        return ground_exceptional_exit(
            exception_name="ZeroDivisionError", site=self.site, owner="BinOp"
        )

    monkeypatch.setattr(CallSiteValue, "_reduce_source_outcome", _reduce_source_outcome)


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
    from sugar_lift_py_tests.outcome import ExitSet

    projected = callsite.project_producer_outcome(ExitSet.completed(TermValue(1)), None)

    assert projected.completed_value() is not None
    assert isinstance(projected.completed_value(), CallSiteValue)
    assert projected.completed_value().retained_source_completion_outcome() == (
        ExitSet.completed(TermValue(1))
    )


def test_the_projection_makes_a_callee_raise_the_calls_halt(callsite) -> None:
    """Since #7821 the ground exit is a halt, not a completed ``RaiseValue``.
    It takes the projection's halt arm, as every other callee raise does:
    one halted face, owned by the Call, and no completion."""
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
    from sugar_lift_py_tests.outcome import ExitSet, Halted

    raised = ground_exceptional_exit(
        exception_name="ZeroDivisionError", site=callsite.site, owner="BinOp"
    )
    assert len(raised.exits) == 1 and raised.halts() == raised.exits

    projected = callsite.project_producer_outcome(raised, None)

    assert isinstance(projected, ExitSet)
    (face,) = projected.exits
    assert isinstance(face, Halted)
    assert face.effect.exception_name == "ZeroDivisionError"
    assert face.effect.producer_node_owner == "Call"


def test_the_projection_stamps_the_call_on_a_raise_with_no_path(callsite) -> None:
    """A typed raise keyed by its ``file:line:col`` locus leaves the callee
    stamped with the frame it was raised in (``occurrence.call_frame_path``),
    so a caller's ``try`` reads which call raised it (#8105).  An occurrence
    that already carries a path keeps it."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.occurrence import call_frame_path
    from sugar_lift_py_tests.outcome import ExitSet, Halted

    frame = "/".join(call_frame_path(callsite.site, callsite.occurrence_path))

    raised = ExitSet.halted(
        RaiseEffect.for_builtin("ValueError", blame="callee.py:2:4")
    )
    (face,) = callsite.project_producer_outcome(raised, None).exits
    assert isinstance(face, Halted)
    assert face.effect.occurrence_id == f"callee.py:2:4@{frame}"
    assert face.effect.producer_node_owner == "Call"

    keyed = ExitSet.halted(
        RaiseEffect.for_builtin("ValueError", occurrence="callee.py:2:4@call:inner")
    )
    (face,) = callsite.project_producer_outcome(keyed, None).exits
    assert face.effect.occurrence_id == "callee.py:2:4@call:inner"
