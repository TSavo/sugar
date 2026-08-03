"""Pre-yield If (guarded setup) execution on the live generator machine.

Real managers use ``if cond: x = …`` before yield. When both branches are
wholly nameable, IfStepV1 runs (ground true/false splice; undecided partition).
Unhandled kinds inside a branch keep the whole If Opaque and loud.
"""

from __future__ import annotations

import tempfile

from sugar_lift_py_tests.floor import NoneValue, TermValue
from sugar_lift_py_tests.generator_construction import (
    AssignStepV1,
    GeneratorAssignBindingV1,
    GeneratorConstructionV1,
    IfStepV1,
    OpaqueStepV1,
    YieldEffect,
)
from sugar_lift_py_tests.outcome.exit_set import ExitSet
from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _steps(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    function = next(SourceFile(path_source(path)).functions())
    return function._source_visible_generator_steps_from(function.body)


def test_pre_yield_if_assign_emits_if_step_then_yield():
    steps = _steps(
        "def g(flag):\n" "    if flag:\n" "        prior = None\n" "    yield 1\n"
    )
    assert isinstance(steps[0], IfStepV1)
    assert isinstance(steps[0].then_steps[0], AssignStepV1)
    assert steps[0].then_steps[0].name == "prior"


def test_ground_true_pre_yield_if_assigns_then_yields():
    steps = _steps(
        "def g():\n" "    if True:\n" "        prior = None\n" "    yield 1\n"
    )
    assert isinstance(steps[0], IfStepV1)
    yielded = GeneratorConstructionV1.allocate(
        allocation_coordinate="enter:if-true",
        frame_coordinate="frame:if-true",
        binding_state=(),
        steps=steps,
    ).resume()
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


def test_ground_false_pre_yield_if_skips_then_yields():
    steps = _steps(
        "def g():\n" "    if False:\n" "        prior = None\n" "    yield 7\n"
    )
    yielded = GeneratorConstructionV1.allocate(
        allocation_coordinate="enter:if-false",
        frame_coordinate="frame:if-false",
        binding_state=(),
        steps=steps,
    ).resume()
    assert isinstance(yielded, YieldEffect)
    assert not any(
        isinstance(b, GeneratorAssignBindingV1) and b.name == "prior"
        for b in yielded.machine.binding_state
    )
    assert yielded.value == TermValue(7)


def test_undecided_pre_yield_if_partitions():
    steps = _steps(
        "def g(flag):\n" "    if flag:\n" "        prior = None\n" "    yield 1\n"
    )
    outcome = GeneratorConstructionV1.allocate(
        allocation_coordinate="enter:if-undecided",
        frame_coordinate="frame:if-undecided",
        binding_state=(),
        steps=steps,
    ).resume()
    assert isinstance(outcome, ExitSet)


def test_if_with_raise_stays_opaque_at_enter():
    steps = _steps(
        "def g(flag):\n"
        "    if flag:\n"
        "        raise ValueError('boom')\n"
        "    yield 1\n"
    )
    assert isinstance(steps[0], OpaqueStepV1)
    assert steps[0].observed == "If"
    from sugar_lift_py_tests.generator_construction import GeneratorTransitionGapV1

    gap = GeneratorConstructionV1.allocate(
        allocation_coordinate="enter:if-raise",
        frame_coordinate="frame:if-raise",
        binding_state=(),
        steps=steps,
    ).resume()
    assert isinstance(gap, GeneratorTransitionGapV1)
    assert "If" in gap.observed


def test_enter_resource_outcome_runs_pre_yield_if_assign():
    from types import SimpleNamespace

    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_python_source.manager_protocol_construction import (
        EnteredGeneratorManagerStateV1,
        construct_generator_backed_protocol,
    )

    steps = _steps(
        "def g():\n" "    if True:\n" "        prior = None\n" "    yield 1\n"
    )
    frame = SimpleNamespace(
        frame_cid=cid_of_json({"f": "pre-yield-if-enter"}),
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
