"""Discharged native-operation halts retain reducer-owned temporal state."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    ReducerPreEffectStateV1,
)
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import ObjectValue, TermValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef, FunctionDef
from sugar_source_tree.tree import SourceFile


SOURCE = (
    "class Widget:\n"
    "    @property\n"
    "    def field(self):\n"
    "        return 1\n"
    "\n"
    "def helper(obj, value):\n"
    "    obj.field = value\n"
)


def _pending_and_receiver():
    tree = SourceFile(
        (SOURCE, "native-operation-state.py", blake3_512_of(SOURCE.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    class_def = next(node for node in tree.nodes() if isinstance(node, ClassDef))
    helper = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "helper"
    )
    class_outcome = class_def.sugar().desugar(None)
    assert isinstance(class_outcome, Complete)
    assert isinstance(class_outcome.value, ClassDefinitionValue)
    receiver = class_outcome.value.construct_receiver_state_from_block(
        None, class_outcome.value.class_definition_cid
    )
    pending = helper.sugar().desugar(None)
    assert isinstance(receiver, ObjectValue)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    return pending, receiver


def _attribute_error_discharge():
    pending, receiver = _pending_and_receiver()
    obj_cid, _, value_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge({obj_cid: receiver, value_cid: TermValue(7)})
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    return pending, receiver, halted


class _Expected:
    def __init__(self, name: str):
        self.identity = ctor(
            "python:exception_type_identity",
            [str_const("builtins"), str_const(name)],
        )

    def exception_type_identity(self):
        return self.identity


def _route(exits: ExitSet, expected: str):
    return exits.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected(expected)),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )


def test_setattr_exception_and_boundary_share_exact_pre_effect_state() -> None:
    pending, _, halted = _attribute_error_discharge()
    testimony = pending.pre_effect_state
    assert testimony is not None
    assert halted.state is testimony.state
    assert halted.effect.exception_name == "AttributeError"
    assert "AttributeError" in repr(halted.effect.exception_type_coordinate)
    assert halted.effect.occurrence_id is not None

    routed = _route(ExitSet((halted,)), "AttributeError")
    assert len(routed.exits) == 1
    completed = routed.exits[0]
    assert isinstance(completed, Completed)
    assert completed.value is testimony.state


def test_wrong_boundary_retains_identical_halt_effect_and_state() -> None:
    _, _, halted = _attribute_error_discharge()

    routed = _route(ExitSet((halted,)), "ValueError")
    assert len(routed.exits) == 1
    retained = routed.exits[0]
    assert isinstance(retained, Halted)
    assert retained.effect is halted.effect
    assert retained.state is halted.state


@pytest.mark.parametrize("lie", ["empty", "receiver", "post-store"])
def test_raw_state_substitutes_are_rejected_at_carrier_enrollment(lie: str) -> None:
    pending, receiver = _pending_and_receiver()
    if lie == "empty":
        substitute = _ReducedBlock((), True, ())
    elif lie == "receiver":
        substitute = receiver
    else:
        completed = receiver.setattr("other", TermValue(9), pending.site)
        assert isinstance(completed, Complete)
        substitute = completed.value

    with pytest.raises(TypeError, match="reducer-issued testimony"):
        pending.and_then(lambda value: Complete(value), pre_effect_state=substitute)


def test_explicit_none_is_rejected_at_carrier_enrollment() -> None:
    pending, _ = _pending_and_receiver()

    with pytest.raises(TypeError, match="reducer-issued testimony"):
        pending.and_then(lambda value: Complete(value), pre_effect_state=None)


def test_second_conflicting_state_enrollment_panics() -> None:
    pending, _ = _pending_and_receiver()
    conflicting = ReducerPreEffectStateV1._from_reducer(
        _ReducedBlock((TermValue(99),), True, ())
    )

    with pytest.raises(ConstructionPanic, match="second conflicting"):
        pending.and_then(
            lambda value: Complete(value),
            pre_effect_state=conflicting,
        )
