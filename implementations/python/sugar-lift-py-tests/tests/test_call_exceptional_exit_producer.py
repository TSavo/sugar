"""Call is an ExitSet producer peer, never an assertion-boundary special case."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile


def _source_file(source: str, context: TreeConstructionContextV1) -> SourceFile:
    return SourceFile(
        (source, "call_exceptional_exit_fixture.py", blake3_512_of(source.encode())),
        construction_context=context,
    )


def _coordinate(node: Call) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _call_outcome(function_body: str):
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        f"def producer():\n{function_body}\n\nproducer()\n",
        context,
    )
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    call = tuple(node for node in source.nodes() if isinstance(node, Call))[-1]
    context.source_call_frames[_coordinate(call)] = function.source_visible_call_frame()
    return call.sugar().desugar(None)


def _parameterized_call_outcome(function_body: str):
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        f"def producer(flag):\n{function_body}\n\nproducer(flag)\n",
        context,
    )
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    call = tuple(node for node in source.nodes() if isinstance(node, Call))[-1]
    context.source_call_frames[_coordinate(call)] = function.source_visible_call_frame()
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

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)


def test_guarded_source_call_preserves_completed_and_halted_faces() -> None:
    outcome = _parameterized_call_outcome(
        "    if flag:\n        raise ValueError()\n    return 7"
    )

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 2
    completed = next(face for face in outcome.exits if isinstance(face, Completed))
    halted = next(face for face in outcome.exits if isinstance(face, Halted))
    assert isinstance(completed.value, CallSiteValue)
    assert isinstance(halted.effect, RaiseEffect)
    assert halted.effect.exception_name == "ValueError"


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
