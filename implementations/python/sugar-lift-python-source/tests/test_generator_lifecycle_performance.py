"""GeneratorBackedManagerProtocolV1 lifecycle performance.

enter_resource_outcome: first yield + exact machine state.
exit_outcome_for: resume that state once; suppression from authenticated exit.

Twins: double-exit refuses; wrong-face resume refuses; suppression only from
exit outcome. No nodes.py / consumer edits.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.generator_construction import (
    GeneratorConstructionV1,
    ReturnStepV1,
    YieldStepV1,
)
from sugar_lift_py_tests.outcome import Complete, outcome_to_exitset
from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.manager_protocol_construction import (
    EnteredGeneratorManagerStateV1,
    GeneratorBackedManagerProtocolV1,
    construct_generator_backed_protocol,
)
from sugar_source_tree.panic import SugarNotWritten


def _coords():
    enter = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 1, 0, 2, 0)
    exit_ = SourceFragmentCoordinateV1("blake3-512:" + "b" * 128, 3, 0, 4, 0)
    return enter, exit_


def _frame(*, steps=None, frame_cid=None, bindings=()):
    if steps is None:
        steps = (YieldStepV1(TermValue(17)), ReturnStepV1(None))
    cid = frame_cid or cid_of_json({"frame": "generator-lifecycle-test"})
    return SimpleNamespace(
        frame_cid=cid,
        generator_steps=steps,
        runtime_entries=bindings,
    )


def _protocol(*, frame=None, construction="blake3-512:" + "c" * 128):
    enter, exit_ = _coords()
    frame = frame or _frame()
    result = construct_generator_backed_protocol(
        frame=frame,
        enter_definition=enter,
        exit_definition=exit_,
        exit_face_id="face-lifecycle",
        construction_cid=construction,
    )
    assert isinstance(result, GeneratorBackedManagerProtocolV1)
    return result


def test_enter_resource_outcome_yields_value_with_exact_machine_state():
    protocol = _protocol()
    outcome = protocol.enter_resource_outcome()
    assert isinstance(outcome, Complete)
    entered = outcome.value
    assert isinstance(entered, EnteredGeneratorManagerStateV1)
    assert entered.enter_value == TermValue(17)
    assert isinstance(entered.machine, GeneratorConstructionV1)
    assert entered.machine.suspended_resume_coordinate is not None
    assert entered.protocol_construction_cid == protocol.protocol_construction_cid
    assert entered.entry_cid.startswith("blake3-512:")


def test_exit_outcome_for_resumes_exact_entered_machine_once():
    protocol = _protocol()
    entered = protocol.enter_resource_outcome().value
    exit_outcome = protocol.exit_outcome_for(entered)
    exits = outcome_to_exitset(exit_outcome)
    assert len(exits.exits) == 1
    face = exits.exits[0]
    assert isinstance(face.value, BlockValue)
    assert face.value.statements[-1] == ReturnValue(TermValue(False))


def test_double_exit_of_same_entered_state_refuses():
    protocol = _protocol()
    entered = protocol.enter_resource_outcome().value
    protocol.exit_outcome_for(entered)
    with pytest.raises(SugarNotWritten, match="double exit"):
        protocol.exit_outcome_for(entered)


def test_wrong_protocol_face_resume_refuses():
    left = _protocol(construction="blake3-512:" + "1" * 128)
    right_frame = _frame(frame_cid=cid_of_json({"frame": "other"}))
    right = _protocol(frame=right_frame, construction="blake3-512:" + "2" * 128)
    entered_left = left.enter_resource_outcome().value
    with pytest.raises(SugarNotWritten, match="protocol construction CID mismatch"):
        right.exit_outcome_for(entered_left)


def test_wrong_entered_type_refuses():
    protocol = _protocol()
    with pytest.raises(TypeError, match="EnteredGeneratorManagerStateV1"):
        protocol.exit_outcome_for(TermValue(0))


def test_suppression_truth_only_from_authenticated_exit_outcome():
    """Exit return is the sole suppression testimony — not a fabricated True."""
    protocol = _protocol()
    entered = protocol.enter_resource_outcome().value
    exit_outcome = protocol.exit_outcome_for(entered)
    block = outcome_to_exitset(exit_outcome).exits[0].value
    assert isinstance(block, BlockValue)
    returned = block.statements[-1]
    assert isinstance(returned, ReturnValue)
    # Ordinary GCM StopIteration path → False; never invented True.
    assert returned.value == TermValue(False)
    assert returned.value != TermValue(True)


def test_identical_enters_mint_distinct_entry_cids_and_each_exits_once():
    protocol = _protocol()
    first = protocol.enter_resource_outcome().value
    second = protocol.enter_resource_outcome().value
    assert first.entry_cid != second.entry_cid
    protocol.exit_outcome_for(first)
    protocol.exit_outcome_for(second)
    with pytest.raises(SugarNotWritten, match="double exit"):
        protocol.exit_outcome_for(first)
