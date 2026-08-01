"""Source-defined subscript stores discharge through authenticated callers."""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import TermValue, TupleValue
from sugar_lift_py_tests.outcome import (
    Completed,
    ExitSet,
    Halted,
    NativeOperationExitCarrierV1,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile


def _tree(source: str) -> SourceFile:
    return SourceFile(
        (source, "setitem_formal_call.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper_and_calls(source: str):
    tree = _tree(source)
    helper = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    calls = tuple(node for node in tree.nodes() if isinstance(node, Call))
    return helper, calls


def _one_face(outcome):
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    return outcome.exits[0]


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


class _Expected:
    def __init__(self, name: str):
        self.identity = _identity(name)

    def exception_type_identity(self):
        return self.identity


def test_helper_alone_retains_setitem_demand_in_projector_order() -> None:
    helper, _calls = _helper_and_calls(
        "def helper(obj, key, value):\n    obj[key] = value\n"
    )

    pending = helper.sugar().desugar(None)

    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"
    assert tuple(value.term.name for value in pending.operands) == (
        "obj",
        "key",
        "value",
    )
    assert pending.demand.operand_coordinate_cids == tuple(
        value.formal_coordinate.coordinate_cid for value in pending.operands
    )


def test_positional_keyword_and_default_callers_complete_same_store_demand() -> None:
    _helper, calls = _helper_and_calls(
        "def helper(obj, key=0, value=9):\n"
        "    obj[key] = value\n\n"
        "helper([0], 0, 9)\n"
        "helper([0], key=0, value=9)\n"
        "helper([0])\n"
    )

    faces = tuple(_one_face(call.sugar().desugar(None)) for call in calls)

    assert len(faces) == 3
    assert all(isinstance(face, Completed) for face in faces)
    values = tuple(face.value for face in faces)
    assert values[0].arg_values == values[1].arg_values == values[2].arg_values
    assert (
        values[0].formal_coordinate_cids
        == values[1].formal_coordinate_cids
        == values[2].formal_coordinate_cids
    )
    assert (
        values[0].source_call_frame_cid
        == values[1].source_call_frame_cid
        == values[2].source_call_frame_cid
    )


def test_immutable_receiver_reads_but_formal_store_halts_with_named_type() -> None:
    helper, calls = _helper_and_calls(
        "def helper(obj, key, value):\n"
        "    obj[key] = value\n\n"
        "helper((0,), 0, 9)\n"
    )
    readable = TupleValue((TermValue(0),)).subscript(TermValue(0), "read.py:1")
    assert readable.value == TermValue(0)
    assert isinstance(helper.sugar().desugar(None), NativeOperationExitCarrierV1)

    halted = _one_face(calls[-1].sugar().desugar(None))

    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("TypeError")
    assert "'startLine': 2" in halted.effect.occurrence
    assert "assertion" not in halted.effect.occurrence


def test_wrong_expected_type_leaves_setitem_exception_unconsumed() -> None:
    _helper, calls = _helper_and_calls(
        "def helper(obj, key, value):\n"
        "    obj[key] = value\n\n"
        "helper((0,), 0, 9)\n"
    )
    produced = calls[-1].sugar().desugar(None)
    original = _one_face(produced)
    assert isinstance(original, Halted)

    routed = produced.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected("IndexError")),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )

    remaining = [
        face
        for face in routed.exits
        if isinstance(face, Halted) and face.effect is original.effect
    ]
    assert remaining == [original]
    assert remaining[0].effect.exception_type_coordinate == _identity("TypeError")
