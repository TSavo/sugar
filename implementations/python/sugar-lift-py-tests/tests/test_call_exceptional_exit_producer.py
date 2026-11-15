"""Call is an ExitSet producer peer, never an assertion-boundary special case."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect import RaiseEffect, UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call
from sugar_source_tree.tree import SourceFile


def _source_file(source: str, context: TreeConstructionContextV1) -> SourceFile:
    return SourceFile(
        (source, "call_exceptional_exit_fixture.py", blake3_512_of(source.encode())),
        construction_context=context,
    )


def _call_outcome(function_body: str):
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        f"def producer():\n{function_body}\n\nproducer()\n",
        context,
    )
    call = tuple(node for node in source.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _parameterized_call_outcome(function_body: str):
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        f"def producer(flag):\n{function_body}\n\nproducer(flag)\n",
        context,
    )
    call = tuple(node for node in source.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def test_authenticated_call_publishes_its_source_body_halt() -> None:
    outcome = _call_outcome("    raise ValueError()")

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert isinstance(halted.effect, RaiseEffect)
    assert halted.effect.exception_name == "ValueError"
    assert halted.effect.producer_node_owner == "Call"


def test_completed_source_call_keeps_the_ordinary_call_coordinate() -> None:
    outcome = _call_outcome("    return 7")

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), CallSiteValue)


def test_guarded_source_call_preserves_completed_and_halted_faces() -> None:
    outcome = _parameterized_call_outcome(
        "    if flag:\n        raise ValueError()\n    return 7"
    )

    assert isinstance(outcome, ExitSet)
    # Three faces, none dropped: ``flag`` is not decided here, so ``if flag``
    # asks its truth, and that operation is itself two-faced.  Where it
    # completes the body either returns or raises ``ValueError``; where it
    # does not, the test's own undetermined raise leaves the call.
    assert len(outcome.exits) == 3
    (completed,) = (face for face in outcome.exits if isinstance(face, Completed))
    halts = [face for face in outcome.exits if isinstance(face, Halted)]
    (raised,) = (face for face in halts if isinstance(face.effect, RaiseEffect))
    (test_halt,) = (
        face for face in halts if isinstance(face.effect, UndeterminedRaiseEffect)
    )
    assert isinstance(completed.value, CallSiteValue)
    assert raised.effect.exception_name == "ValueError"
    assert test_halt.effect.exception_name is None


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
