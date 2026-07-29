"""GeneratorBackedManagerProtocolV1 lifecycle performance.

enter_resource_outcome: first yield + exact machine state.
exit_outcome_for: resume that state once; suppression from authenticated exit.

Twins: double-exit refuses; wrong-face resume refuses; suppression only from
exit outcome.

Pre-yield exceptional twins (ready for grok-1 item-1): inert steps before
yield already green; ``Assign`` / suspension-carrying opaque pre-yield are
honorable reds naming the remaining transition producer; never-yield enter
refusal stays green as the exceptional control.

No nodes.py / consumer edits.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, StringValue, TermValue
from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.generator_construction import (
    GeneratorConstructionV1,
    InertStepV1,
    OpaqueStepV1,
    ReturnStepV1,
    YieldEffect,
    YieldStepV1,
)
from sugar_lift_py_tests.outcome import Complete, Incomplete, outcome_to_exitset
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted, partition
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar
from sugar_lift_py_tests.sugar.string_literal_sugar import StringLiteralSugar
from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.manager_protocol_construction import (
    EnteredGeneratorManagerStateV1,
    GeneratorBackedManagerProtocolV1,
    _project_generator_enter_result,
    construct_generator_backed_protocol,
)
from sugar_source_tree.panic import SugarNotWritten


def _coords():
    enter = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 1, 0, 2, 0)
    exit_ = SourceFragmentCoordinateV1("blake3-512:" + "b" * 128, 3, 0, 4, 0)
    return enter, exit_


def _frame(*, steps=None, frame_cid=None, bindings=()):
    if steps is None:
        steps = (
            YieldStepV1(IntLiteralSugar(17, site="yield:17")),
            ReturnStepV1(None),
        )
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


def test_enter_bound_generator_construction_preserves_exact_machine_testimony():
    protocol = _protocol()
    reduction_context = ReduceContext.root(owner="already-bound-generator")
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:already-bound-generator",
        frame_coordinate=protocol.generator_frame_cid,
        binding_state=(),
        steps=protocol.generator_frame.generator_steps,
        reduction_context=reduction_context,
    )

    outcome = protocol.enter_resource_outcome_for(machine)

    assert isinstance(outcome, Complete)
    entered = outcome.value
    assert entered.machine.instance_coordinate == machine.instance_coordinate
    assert entered.machine.allocation_coordinate == machine.allocation_coordinate
    assert entered.machine.reduction_context is reduction_context


def test_enter_bound_generator_construction_refuses_foreign_frame():
    protocol = _protocol()
    foreign = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:foreign-generator",
        frame_coordinate=cid_of_json({"frame": "foreign-generator"}),
        binding_state=(),
        steps=protocol.generator_frame.generator_steps,
    )

    with pytest.raises(SugarNotWritten, match="frame coordinate"):
        protocol.enter_resource_outcome_for(foreign)


def test_enter_bound_generator_sequences_mixed_yield_and_halt_faces():
    true_face, false_face = partition("mixed-enter-guard")
    effect = RaiseEffect(
        exception_name="RenamedError",
        blame="mixed-enter",
        occurrence="mixed-enter:halt",
    )
    state = TermValue("pre-enter-state")
    pending = ()

    class MixedGuardSugar(ConstructedTermSugar):
        @classmethod
        def witnesses(cls):
            return ()

        def desugar(self, ctx=None):
            del ctx
            from sugar_lift_py_tests.ir import atomic
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return ExitSet(
                (
                    Completed(
                        atomic("mixed-enter-completed", []),
                        TrueBoolLiteralSugar(site="mixed-enter:true"),
                        frozenset({true_face}),
                        (),
                    ),
                    Halted(
                        atomic("mixed-enter-halted", []),
                        effect,
                        state,
                        frozenset({false_face}),
                        pending,
                    ),
                )
            )

        def to_term(self, *, owner: str):
            from sugar_lift_py_tests.ir import ctor

            return ctor("mixed-enter-guard", (), symbol_kind="predicate")

    from sugar_lift_py_tests.generator_construction import IfStepV1

    protocol = _protocol()
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:mixed-enter",
        frame_coordinate=protocol.generator_frame_cid,
        binding_state=(),
        steps=(
            IfStepV1(
                MixedGuardSugar(),
                (YieldStepV1(IntLiteralSugar(31, site="yield:31")),),
                (),
                "mixed-enter:if",
            ),
            ReturnStepV1(None),
        ),
    )

    outcome = protocol.enter_resource_outcome_for(machine)

    completed = tuple(face for face in outcome.exits if isinstance(face, Completed))
    halted = tuple(face for face in outcome.exits if isinstance(face, Halted))
    assert len(completed) == 1
    assert isinstance(completed[0].value, EnteredGeneratorManagerStateV1)
    assert completed[0].value.enter_value == TermValue(31)
    assert len(halted) == 1
    assert halted[0].effect is effect
    assert halted[0].state is state
    assert halted[0].faces == frozenset({false_face})
    assert halted[0].pending_contracts is pending


def test_enter_projector_resumes_guarded_branch_machines_once():
    from sugar_lift_py_tests.ir import atomic

    guard = atomic("guarded-enter-yields", [])
    protocol = _protocol()
    true_machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:guarded-enter:true",
        frame_coordinate=protocol.generator_frame_cid,
        binding_state=(),
        steps=(YieldStepV1(IntLiteralSugar(41, site="yield:41")),),
    )
    false_machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:guarded-enter:false",
        frame_coordinate=protocol.generator_frame_cid,
        binding_state=(),
        steps=(YieldStepV1(IntLiteralSugar(43, site="yield:43")),),
    )
    result = GuardedValue(
        guard,
        true_machine,
        false_machine,
    )

    outcome = _project_generator_enter_result(protocol, true_machine, result)

    assert isinstance(outcome, ExitSet)
    completed = tuple(face for face in outcome.exits if isinstance(face, Completed))
    assert len(completed) == 2
    assert {face.value.enter_value for face in completed} == {
        TermValue(41),
        TermValue(43),
    }
    assert all(
        isinstance(face.value, EnteredGeneratorManagerStateV1)
        for face in completed
    )
    assert true_machine.cursor == 0
    assert false_machine.cursor == 0
    assert all(face.value.machine.cursor == 1 for face in completed)


def test_enter_projector_distributes_guarded_yield_effect_arms_secondarily():
    from sugar_lift_py_tests.ir import atomic

    guard = atomic("guarded-enter-direct-yields", [])
    protocol = _protocol()
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:guarded-enter-direct",
        frame_coordinate=protocol.generator_frame_cid,
        binding_state=(),
        steps=(YieldStepV1(IntLiteralSugar(53, site="yield:53")),),
    )
    true_effect = machine.resume()
    false_machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:guarded-enter-direct:false",
        frame_coordinate=protocol.generator_frame_cid,
        binding_state=(),
        steps=(YieldStepV1(IntLiteralSugar(59, site="yield:59")),),
    )
    false_effect = false_machine.resume()
    assert isinstance(true_effect, YieldEffect)
    assert isinstance(false_effect, YieldEffect)
    result = GuardedValue(
        guard,
        true_effect,
        false_effect,
    )

    outcome = _project_generator_enter_result(protocol, machine, result)

    assert isinstance(outcome, ExitSet)
    assert {
        face.value.enter_value
        for face in outcome.exits
        if isinstance(face, Completed)
    } == {TermValue(53), TermValue(59)}


def test_enter_projector_refuses_foreign_guarded_branch_machine():
    from sugar_lift_py_tests.ir import atomic

    guard = atomic("guarded-enter-foreign-machine", [])
    protocol = _protocol()
    local = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:guarded-enter:local",
        frame_coordinate=protocol.generator_frame_cid,
        binding_state=(),
        steps=(YieldStepV1(IntLiteralSugar(61, site="yield:61")),),
    )
    foreign = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:guarded-enter:foreign",
        frame_coordinate=cid_of_json({"frame": "foreign-guarded-arm"}),
        binding_state=(),
        steps=(YieldStepV1(IntLiteralSugar(67, site="yield:67")),),
    )

    with pytest.raises(SugarNotWritten, match="frame coordinate"):
        _project_generator_enter_result(
            protocol,
            local,
            GuardedValue(guard, local, foreign),
        )


def test_enter_projector_keeps_unsupported_guarded_arm_loud():
    from sugar_lift_py_tests.ir import atomic

    guard = atomic("guarded-enter-bad-arm", [])
    protocol = _protocol()
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:guarded-enter-bad-arm",
        frame_coordinate=protocol.generator_frame_cid,
        binding_state=(),
        steps=(YieldStepV1(IntLiteralSugar(47, site="yield:47")),),
    )
    good_effect = machine.resume()
    assert isinstance(good_effect, YieldEffect)
    result = GuardedValue(
        guard,
        good_effect,
        TermValue("not-a-generator-transition"),
    )

    with pytest.raises(SugarNotWritten, match="YieldEffect"):
        _project_generator_enter_result(protocol, machine, result)


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


# ---------------------------------------------------------------------------
# Pre-yield exceptional twins — green core + reds waiting on grok-1 item-1
# ---------------------------------------------------------------------------


def test_pre_yield_inert_step_then_yield_still_enters():
    """Control: statements that owe nothing are stepped past before first yield."""
    protocol = _protocol(
        frame=_frame(
            steps=(
                InertStepV1("Expr"),
                InertStepV1("Pass"),
                YieldStepV1(IntLiteralSugar(99, site="yield:99")),
                ReturnStepV1(None),
            ),
            frame_cid=cid_of_json({"frame": "pre-yield-inert"}),
        )
    )
    outcome = protocol.enter_resource_outcome()
    assert isinstance(outcome, Complete)
    assert outcome.value.enter_value == TermValue(99)
    assert isinstance(outcome.value, EnteredGeneratorManagerStateV1)
    # Exit still once after inert-prefix enter.
    exit_outcome = protocol.exit_outcome_for(outcome.value)
    face = outcome_to_exitset(exit_outcome).exits[0]
    assert face.value.statements[-1] == ReturnValue(TermValue(False))


def test_pre_yield_never_yield_is_authenticated_entry_refusal():
    """Exceptional control: return before any yield → Incomplete entry raise."""
    protocol = _protocol(
        frame=_frame(
            steps=(ReturnStepV1(None),),
            frame_cid=cid_of_json({"frame": "never-yield"}),
        )
    )
    outcome = protocol.enter_resource_outcome()
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RaiseEffect)
    assert outcome.effect.exception_name == "RuntimeError"
    # Message is vendor-observed refusal, not a silent gap.
    assert outcome.effect.raised_value is not None
    assert "yield" in str(outcome.effect.raised_value).lower()


def test_pre_yield_assign_then_yield_enters_with_resource():
    """LAW (item-1): ordinary pre-yield Assign is performed, then yield enters.

    Live shapes from the renamed consumption suite are exactly this row:

        prior = None
        yield (key, value, prior)

    AssignStepV1 executes on the live machine; enter completes with the yield
    value and an exact machine state that can exit once.
    """
    from sugar_lift_py_tests.generator_construction import AssignStepV1

    protocol = _protocol(
        frame=_frame(
            steps=(
                AssignStepV1(
                    "prior", NoneLiteralSugar(site="assign:prior"), "frag:prior"
                ),
                YieldStepV1(IntLiteralSugar(42, site="yield:42")),
                ReturnStepV1(None),
            ),
            frame_cid=cid_of_json({"frame": "pre-yield-assign"}),
        )
    )
    outcome = protocol.enter_resource_outcome()
    assert isinstance(outcome, Complete), type(outcome)
    entered = outcome.value
    assert isinstance(entered, EnteredGeneratorManagerStateV1)
    assert entered.enter_value == TermValue(42)
    assert entered.machine.suspended_resume_coordinate is not None
    # Exit must still be one-shot after Assign-prefix enter.
    protocol.exit_outcome_for(entered)
    with pytest.raises(SugarNotWritten, match="double exit"):
        protocol.exit_outcome_for(entered)


def test_pre_yield_suspension_assign_twin_does_not_impersonate_ordinary_assign():
    """Discrimination twin: Assign *carrying a suspension* is not ordinary bind.

    ``x = yield v`` is generator-protocol work (resume value binding), not the
    same obligation as ``x = 1`` before a later yield. Today both may gap; when
    ordinary Assign greens, this twin must still refuse silent step-over of a
    suspension-carrying Assign — either enter on the yield inside, or loud gap
    naming suspension, never a fabricated enter that dropped the yield.
    """
    protocol = _protocol(
        frame=_frame(
            steps=(
                OpaqueStepV1("Assign", carries_suspension=True),
                # Trailing yield only if suspension Assign is wrongly skipped.
                YieldStepV1(
                    StringLiteralSugar(
                        "should-not-steal", site="yield:should-not-steal"
                    )
                ),
                ReturnStepV1(None),
            ),
            frame_cid=cid_of_json({"frame": "pre-yield-suspension-assign"}),
        )
    )
    try:
        outcome = protocol.enter_resource_outcome()
    except SugarNotWritten as gap:
        # Honest residual until suspension-carrying Assign is constructed.
        assert "Assign" in str(gap.observed) or "suspension" in str(gap.observed).lower(), (
            gap.observed
        )
        assert "carrying a suspension" in str(gap.observed) or gap.observed == "Assign" or (
            "Assign carrying a suspension" in str(gap.observed)
        ), (
            f"suspension twin must name suspension-carrying Assign, not a foreign "
            f"shape; observed={gap.observed!r}"
        )
        return
    # If enter somehow completes, it must be from the *inner* yield of the
    # suspension Assign — never by skipping to the trailing YieldStep.
    assert isinstance(outcome, Complete)
    entered = outcome.value
    assert isinstance(entered, EnteredGeneratorManagerStateV1)
    # Trailing "should-not-steal" would mean the suspension Assign was skipped.
    assert entered.enter_value != StringValue("should-not-steal"), (
        "suspension-carrying Assign was stepped past as if inert; resume-value "
        "binding was dropped"
    )


def test_pre_yield_assign_and_inert_prefix_compose_then_yield():
    """Composed pre-yield: inert + Assign + yield."""
    from sugar_lift_py_tests.generator_construction import AssignStepV1

    protocol = _protocol(
        frame=_frame(
            steps=(
                InertStepV1("Expr"),
                AssignStepV1(
                    "prior", NoneLiteralSugar(site="assign:prior2"), "frag:prior2"
                ),
                YieldStepV1(IntLiteralSugar(7, site="yield:7")),
                ReturnStepV1(None),
            ),
            frame_cid=cid_of_json({"frame": "inert-then-assign-then-yield"}),
        )
    )
    outcome = protocol.enter_resource_outcome()
    assert isinstance(outcome, Complete)
    assert outcome.value.enter_value == TermValue(7)
