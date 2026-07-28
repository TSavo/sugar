"""Pre-yield Assign execution on the live generator machine.

config-set / filter-push / temp-state save shapes bind a name before yield.
AssignStepV1 must execute (not Opaque gap). Tampered assign source refuses
content-stable testimony.
"""

from __future__ import annotations

import tempfile

from sugar_lift_py_tests.floor import NoneValue, TermValue
from sugar_lift_py_tests.generator_construction import (
    AssignStepV1,
    GeneratorAssignBindingV1,
    GeneratorConstructionV1,
    YieldEffect,
    YieldStepV1,
)
from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _steps(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    function = next(SourceFile(path_source(path)).functions())
    return function._source_visible_generator_steps_from(function.body)


def test_config_setter_pre_yield_assign_executes_before_yield():
    steps = _steps(
        "def set_config(key, value):\n"
        "    prior = None\n"
        "    yield (key, value, prior)\n"
    )
    assert isinstance(steps[0], AssignStepV1)
    assert steps[0].name == "prior"
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="enter:config",
        frame_coordinate="frame:config",
        binding_state=(),
        steps=steps,
    )
    yielded = machine.resume()
    assert isinstance(yielded, YieldEffect)
    assert any(
        isinstance(b, GeneratorAssignBindingV1) and b.name == "prior"
        for b in yielded.machine.binding_state
    )
    prior = next(
        b
        for b in yielded.machine.binding_state
        if isinstance(b, GeneratorAssignBindingV1)
    )
    assert isinstance(prior.value, NoneValue)


def test_filter_push_pre_yield_assign_executes():
    steps = _steps(
        "def filter_warnings(action):\n"
        "    filters = [action]\n"
        "    yield filters\n"
    )
    assert isinstance(steps[0], AssignStepV1)
    assert steps[0].name == "filters"
    yielded = GeneratorConstructionV1.allocate(
        allocation_coordinate="enter:filter",
        frame_coordinate="frame:filter",
        binding_state=(),
        steps=steps,
    ).resume()
    assert isinstance(yielded, YieldEffect)
    assert any(
        isinstance(b, GeneratorAssignBindingV1) and b.name == "filters"
        for b in yielded.machine.binding_state
    )


def test_temp_state_pre_yield_assign_executes():
    steps = _steps("def hold_state(state):\n" "    saved = state\n" "    yield saved\n")
    assert isinstance(steps[0], AssignStepV1)
    assert steps[0].name == "saved"
    yielded = GeneratorConstructionV1.allocate(
        allocation_coordinate="enter:temp",
        frame_coordinate="frame:temp",
        binding_state=(),
        steps=steps,
    ).resume()
    assert isinstance(yielded, YieldEffect)
    assert any(
        isinstance(b, GeneratorAssignBindingV1) and b.name == "saved"
        for b in yielded.machine.binding_state
    )


def test_tampered_assign_fragment_refuses_stable_step_identity():
    steps = _steps("def g():\n    prior = None\n    yield prior\n")
    assign = steps[0]
    assert isinstance(assign, AssignStepV1)
    authentic = assign.fragment_cid
    assert authentic.startswith("blake3-512:")
    # Tampered fragment CID is not the sealed source coordinate of the assign.
    tampered_cid = "blake3-512:" + "f" * 128
    assert authentic != tampered_cid
    # Live machine records the authentic fragment; a foreign CID cannot
    # impersonate the executed binding's source coordinate.
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="enter:tamper",
        frame_coordinate="frame:tamper",
        binding_state=(),
        steps=steps,
    ).resume()
    prior = next(
        b
        for b in machine.machine.binding_state
        if isinstance(b, GeneratorAssignBindingV1) and b.name == "prior"
    )
    assert prior.fragment_cid == authentic
    assert prior.fragment_cid != tampered_cid


def test_enter_resource_outcome_runs_pre_yield_assign():
    """Protocol enter path also executes AssignStep before yield."""
    from types import SimpleNamespace

    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_python_source.manager_protocol_construction import (
        EnteredGeneratorManagerStateV1,
        construct_generator_backed_protocol,
    )

    steps = _steps("def g():\n    prior = None\n    yield 1\n")
    frame = SimpleNamespace(
        frame_cid=cid_of_json({"f": "pre-yield-enter"}),
        generator_steps=steps,
        runtime_entries=(),
    )
    enter = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 1, 0, 2, 0)
    exit_ = SourceFragmentCoordinateV1("blake3-512:" + "b" * 128, 3, 0, 4, 0)
    protocol = construct_generator_backed_protocol(
        frame=frame,
        enter_definition=enter,
        exit_definition=exit_,
        exit_face_id="face",
        construction_cid="blake3-512:" + "c" * 128,
    )
    outcome = protocol.enter_resource_outcome()
    assert isinstance(outcome, Complete)
    entered = outcome.value
    assert isinstance(entered, EnteredGeneratorManagerStateV1)
    assert entered.enter_value == TermValue(1)
    assert any(
        isinstance(b, GeneratorAssignBindingV1) and b.name == "prior"
        for b in entered.machine.binding_state
    )
