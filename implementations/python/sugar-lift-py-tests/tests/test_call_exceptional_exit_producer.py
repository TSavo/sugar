"""Call is an ExitSet producer peer, never an assertion-boundary special case."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect import RaiseEffect, UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile


def _source_file(source: str, context: TreeConstructionContextV1) -> SourceFile:
    return SourceFile(
        (source, "call_exceptional_exit_fixture.py", blake3_512_of(source.encode())),
        construction_context=context,
    )


def _call_and_callee(signature: str, function_body: str, actuals: str):
    """``producer(<actuals>)`` and ``producer``'s own reduction.

    #7757 step 5 (#8705, the owner's ruling "Edge, join at prove"): a call
    of a same-file def is its coordinate and edge, the one unanswered call
    -- it completes under its ``python:unknown_callee_call.completes`` atom
    with ``python:call_result(<call term>, <occurrence>)`` and halts under
    the complement naming nothing -- never ``producer``'s body applied at
    the call.  What the body raises is ``producer``'s own reduction, which
    its contract states (each halt a panic locus) and prove joins at the
    call (#8690, #8749).  Before #8705 these tests read the body's halts and
    completion off the call."""
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        f"def producer({signature}):\n{function_body}\n\nproducer({actuals})\n",
        context,
    )
    call = tuple(node for node in source.nodes() if isinstance(node, Call))[-1]
    outcome = call.sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 2
    (completed,) = (face for face in outcome.exits if isinstance(face, Completed))
    (halted,) = outcome.halts()
    assert completed.guard.name == "python:unknown_callee_call.completes"
    assert isinstance(completed.value, CallSiteValue)
    assert completed.value.body is None
    assert type(halted.effect) is UndeterminedRaiseEffect
    assert halted.effect.exception_name is None
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    return completed, halted, function.sugar().desugar(None)


def test_authenticated_call_publishes_its_source_body_halt() -> None:
    _completed, halted, callee = _call_and_callee("", "    raise ValueError()", "")

    assert halted.effect.producer_node_owner.startswith("UnknownCallee:")
    assert isinstance(callee, ExitSet)
    (raised,) = callee.halts()
    assert isinstance(raised.effect, RaiseEffect)
    assert raised.effect.exception_name == "ValueError"


def test_completed_source_call_keeps_the_ordinary_call_coordinate() -> None:
    completed, _halted, _callee = _call_and_callee("", "    return 7", "")

    assert completed.value.term.name == "python:call_result"
    assert completed.value.term.args[0].name.startswith("call:")


def test_guarded_source_call_preserves_completed_and_halted_faces() -> None:
    _completed, _halted, callee = _call_and_callee(
        "flag", "    if flag:\n        raise ValueError()\n    return 7", "1"
    )

    # The callee's own reduction keeps its faces, none dropped: ``flag`` is
    # not decided there, so ``if flag`` asks its truth, and that operation is
    # itself two-faced.  Where it completes the body either returns or raises
    # ``ValueError``; where it does not, the test's own undetermined raise.
    assert isinstance(callee, ExitSet)
    halts = callee.halts()
    (raised,) = (face for face in halts if isinstance(face.effect, RaiseEffect))
    assert raised.effect.exception_name == "ValueError"
    assert any(isinstance(face.effect, UndeterminedRaiseEffect) for face in halts)
    assert any(isinstance(face, Completed) for face in callee.exits)


def test_runtime_truthful_and_lying_twins_discriminate() -> None:
    def truthful():
        raise ValueError()

    def lying():
        return 7

    def raises_value_error(thunk) -> bool:
        try:
            thunk()
        except ValueError:
            return True
        return False

    with pytest.raises(ValueError):
        truthful()
    assert lying() == 7
    with pytest.raises(AssertionError):
        assert raises_value_error(lying)
