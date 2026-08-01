"""Formal native operations use the one Python call binder."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import (
    Completed,
    ExitSet,
    Halted,
    NativeOperationExitCarrierV1,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _tree(source: str) -> SourceFile:
    return SourceFile(
        (source, "formal_binding.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _call_outcome(signature: str, actuals: str):
    source = (
        f"def helper({signature}):\n"
        "    return left + right\n\n"
        f"helper({actuals})\n"
    )
    tree = _tree(source)
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _call_outcomes(signature: str, *actuals: str):
    calls = "".join(f"helper({value})\n" for value in actuals)
    source = f"def helper({signature}):\n    return left + right\n\n{calls}"
    tree = _tree(source)
    nodes = tuple(node for node in tree.nodes() if isinstance(node, Call))
    return tuple(node.sugar().desugar(None) for node in nodes)


def _assert_named_halt(outcome) -> None:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate is not None


def test_positional_actuals_discharge_through_python_binder() -> None:
    _assert_named_halt(_call_outcome("left, right", "None, 2"))


def test_keyword_actuals_discharge_through_python_binder() -> None:
    _assert_named_halt(_call_outcome("left, right", "left=None, right=2"))


def test_default_actual_is_keyed_to_its_formal_coordinate() -> None:
    _assert_named_halt(_call_outcome("left, right=2", "None"))


def test_helper_alone_retains_the_undischarged_binary_carrier() -> None:
    source = "def helper(left, right=2):\n    return left + right\n"
    function = next(
        node for node in _tree(source).nodes() if isinstance(node, FunctionDef)
    )
    pending = function.sugar().desugar(None)

    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "add"
    assert all(pending.demand.operand_coordinate_cids)


def test_positional_keyword_and_default_calls_reach_the_same_binary_demand() -> None:
    positional, keyword, default = _call_outcomes(
        "left, right=2", "None, 2", "None, right=2", "None"
    )

    halted = []
    for outcome in (positional, keyword, default):
        _assert_named_halt(outcome)
        halted.append(outcome.exits[0])
    assert {exit_.effect.exception_type_coordinate for exit_ in halted} == {
        halted[0].effect.exception_type_coordinate
    }
    assert {exit_.effect.occurrence_id for exit_ in halted} == {
        halted[0].effect.occurrence_id
    }


def test_keyword_and_default_calls_can_complete_from_the_existing_floor() -> None:
    keyword, default = _call_outcomes("left, right=2", "1, right=2", "1")

    assert all(
        isinstance(outcome, ExitSet)
        and len(outcome.exits) == 1
        and isinstance(outcome.exits[0], Completed)
        for outcome in (keyword, default)
    )


class _Expected:
    def __init__(self, name: str):
        self.identity = ctor(
            "python:exception_type_identity",
            [str_const("builtins"), str_const(name)],
        )

    def exception_type_identity(self):
        return self.identity


def test_wrong_boundary_type_leaves_named_binary_exception_unconsumed() -> None:
    outcome = _call_outcome("left, right=2", "None")
    _assert_named_halt(outcome)
    original = outcome.exits[0]

    routed = outcome.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected("ValueError")),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )

    assert len(routed.exits) == 1
    escaped = routed.exits[0]
    assert isinstance(escaped, Halted)
    assert escaped.effect.exception_type_coordinate == _Expected("TypeError").identity
    assert escaped.effect.exception_type_coordinate != _Expected("ValueError").identity
    assert escaped.effect.occurrence_id == original.effect.occurrence_id


def test_wrong_coordinate_actual_cannot_discharge_pending_operation() -> None:
    source = "def helper(left, right):\n    return left + right\n"
    function = next(
        node for node in _tree(source).nodes() if isinstance(node, FunctionDef)
    )
    pending = function.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    left, right = function.formal_coordinates()

    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge(
            {
                f"wrong:{left.coordinate_cid}": TermValue(1),
                right.coordinate_cid: TermValue(2),
            }
        )
