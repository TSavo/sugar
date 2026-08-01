"""Test-first law for nonlinear generator ``If`` guard outcomes.

The guard producer and the branch transition are two distinct callbacks.  A
producer ExitSet/carrier first projects each Completed operand through
``_guard_truth`` exactly once; only the resulting truth values transition the
branch.  Halted faces bypass both callbacks and retain all testimony.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import GuardedValue, PredicateValue, TermValue
from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.generator_construction import (
    AssignStepV1,
    GeneratorConstructionV1,
    IfStepV1,
    OpaqueStepV1,
    YieldEffect,
    YieldStepV1,
)
from sugar_lift_py_tests.ir import and_, atomic, implies, not_
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted, Incomplete
from sugar_lift_py_tests.outcome.exit_set import partition
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _Pending:
    candidate_cid: str
    demands: tuple = ()


@dataclass(frozen=True)
class _OutcomeGuard(ConstructedTermSugar):
    outcome: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    def to_term(self, *, owner: str):
        del owner
        return TermValue(101).to_term(owner="guard producer")


@dataclass(frozen=True)
class _TruthOperand(FloorValue):
    projected: object
    calls: list[object] = field(compare=False, repr=False)

    def truth(self, site):
        self.calls.append(site)
        return self.projected

    def to_term(self, *, owner: str):
        del owner
        return TermValue(102).to_term(owner="truth operand")


@dataclass(frozen=True)
class _CarrierReceiver(FloorValue):
    projected: ExitSet

    def equals(self, other, site):
        del other, site
        return self.projected

    def to_term(self, *, owner: str):
        del owner
        return TermValue(103).to_term(owner="carrier receiver")


def _machine(step: IfStepV1):
    return GeneratorConstructionV1.allocate(
        allocation_coordinate="call:if-guard-outcomes",
        frame_coordinate="frame:if-guard-outcomes",
        binding_state=(),
        steps=(step,),
    )


def _step(guard) -> IfStepV1:
    return IfStepV1(
        guard,
        (YieldStepV1(IntLiteralSugar(1, site="yield:then")),),
        (YieldStepV1(IntLiteralSugar(2, site="yield:else")),),
        "if:guard-outcomes",
    )


def _halt(name: str, *, pending=()):
    left, _ = partition(("if-guard-halt", name))
    return Halted(
        atomic(f"guard:halted:{name}", []),
        RaiseEffect.for_builtin(f"{name}Error", occurrence=f"guard:{name}"),
        state=object(),
        faces=frozenset({left}),
        pending_contracts=pending,
    )


def _assert_halt_identity(actual, expected) -> None:
    assert actual is expected
    assert actual.effect is expected.effect
    assert actual.state is expected.state
    assert actual.guard is expected.guard
    assert actual.faces is expected.faces
    assert actual.pending_contracts is expected.pending_contracts


def _transition_truth_spy(monkeypatch):
    calls: list[object] = []
    original = GeneratorConstructionV1._decide_guard

    def decide(self, truth):
        calls.append(truth)
        return original(self, truth)

    monkeypatch.setattr(GeneratorConstructionV1, "_decide_guard", decide)
    return calls


def test_four_face_guard_projects_completed_operands_once_then_transitions(
    monkeypatch,
) -> None:
    """Synthetic four-face law: two halts, predicate, guarded predicate."""
    halted_left = _halt("left", pending=(_Pending("pending:left"),))
    halted_right = _halt("right", pending=(_Pending("pending:right"),))
    direct_formula = atomic("guard:direct-truth", [])
    inner_true_formula = atomic("guard:inner:true", [])
    inner_false_formula = atomic("guard:inner:false", [])
    outer_formula = atomic("guard:outer", [])
    direct_calls: list[object] = []
    inner_true_calls: list[object] = []
    inner_false_calls: list[object] = []
    direct = _TruthOperand(Complete(PredicateValue(direct_formula)), direct_calls)
    guarded = GuardedValue(
        outer_formula,
        _TruthOperand(Complete(PredicateValue(inner_true_formula)), inner_true_calls),
        _TruthOperand(Complete(PredicateValue(inner_false_formula)), inner_false_calls),
    )
    direct_face, guarded_face = partition("if-guard-completed")
    direct_pending = (_Pending("pending:direct"),)
    guarded_pending = (_Pending("pending:guarded"),)
    direct_prefix_guard = atomic("guard:direct-prefix", [])
    guarded_prefix_guard = atomic("guard:guarded-prefix", [])
    guard_outcome = ExitSet(
        (
            halted_left,
            halted_right,
            Completed(
                direct_prefix_guard,
                direct,
                frozenset({direct_face}),
                direct_pending,
            ),
            Completed(
                guarded_prefix_guard,
                guarded,
                frozenset({guarded_face}),
                guarded_pending,
            ),
        )
    )
    transition_calls = _transition_truth_spy(monkeypatch)
    step = _step(_OutcomeGuard(guard_outcome))
    machine = _machine(step)
    then_face, else_face = partition(
        ("generator.branch", machine.instance_coordinate, step.fragment_cid)
    )

    outcome = machine.resume()

    assert isinstance(outcome, ExitSet)
    assert direct_calls == [machine.instance_coordinate]
    assert inner_true_calls == [machine.instance_coordinate]
    assert inner_false_calls == [machine.instance_coordinate]
    assert direct_calls[0] is machine.instance_coordinate
    assert inner_true_calls[0] is machine.instance_coordinate
    assert inner_false_calls[0] is machine.instance_coordinate
    assert len(transition_calls) == 2
    assert transition_calls[0].formula is direct_formula
    _assert_halt_identity(outcome.exits[0], halted_left)
    _assert_halt_identity(outcome.exits[1], halted_right)
    completed = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert len(completed) == 2
    assert completed[0].pending_contracts is direct_pending
    assert completed[1].pending_contracts is guarded_pending
    assert {direct_face, then_face, else_face} <= completed[0].faces
    assert {guarded_face, then_face, else_face} <= completed[1].faces
    for arm in completed:
        assert isinstance(arm.value, GuardedValue)
        assert isinstance(arm.value.when_true, YieldEffect)
        assert isinstance(arm.value.when_false, YieldEffect)
        assert arm.value.when_true.machine.cursor == 1
        assert arm.value.when_false.machine.cursor == 1
    expected_guarded_truth = and_(
        [
            implies(outer_formula, inner_true_formula),
            implies(not_(outer_formula), inner_false_formula),
        ]
    )
    assert transition_calls[1].formula == expected_guarded_truth
    assert completed[1].value.guard == expected_guarded_truth
    assert completed[0].guard is direct_prefix_guard
    assert completed[1].guard is guarded_prefix_guard


def test_guarded_incomplete_arm_becomes_halted_without_running_branch() -> None:
    calls: list[object] = []
    incomplete = Incomplete(
        RaiseEffect.for_builtin("InnerError", occurrence="guard:inner")
    )
    operand = _TruthOperand(incomplete, calls)
    outer = atomic("guard:outer-incomplete", [])
    guarded = GuardedValue(
        outer,
        operand,
        _TruthOperand(Complete(PredicateValue(atomic("guard:unused", []))), []),
    )
    prefix_pending = (_Pending("pending:guarded-incomplete"),)
    guard_outcome = ExitSet(
        (
            Completed(
                atomic("guard:prefix-incomplete", []),
                guarded,
                pending_contracts=prefix_pending,
            ),
        )
    )

    step = _step(_OutcomeGuard(guard_outcome))
    machine = _machine(step)
    outcome = machine.resume()

    assert isinstance(outcome, ExitSet)
    assert calls == [machine.instance_coordinate]
    assert calls[0] is machine.instance_coordinate
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect is incomplete.effect
    assert halted.pending_contracts == prefix_pending


def _assert_transition_refusal(raised, step, *, observed: str, requested: str):
    assert raised.value.owner == "GeneratorConstructionV1.transition"
    assert raised.value.blame is step
    assert raised.value.observed == observed
    assert raised.value.requested == requested
    assert raised.value.fix == (
        "implement that next branch transition before deferred normalization"
    )


def test_nonlinear_guard_none_transition_is_exact_typed_refusal() -> None:
    calls: list[object] = []
    operand = _TruthOperand(None, calls)
    guard_outcome = ExitSet((Completed(atomic("guard:bad", []), operand),))
    step = _step(_OutcomeGuard(guard_outcome))
    machine = _machine(step)

    with pytest.raises(SugarNotWritten) as raised:
        machine.resume()

    assert calls == [machine.instance_coordinate]
    assert calls[0] is machine.instance_coordinate
    _assert_transition_refusal(
        raised,
        step,
        observed="If carrying a suspension",
        requested="resume",
    )


def test_nonlinear_guard_gap_transition_is_exact_typed_refusal() -> None:
    operand = _TruthOperand(Complete(TrueBoolLiteralSugar(site="guard:true")), [])
    guard_outcome = ExitSet((Completed(atomic("guard:gap", []), operand),))
    step = IfStepV1(
        _OutcomeGuard(guard_outcome),
        (OpaqueStepV1("branch-gap"),),
        (),
        "if:guard-outcomes",
    )

    with pytest.raises(SugarNotWritten) as raised:
        _machine(step).resume()

    _assert_transition_refusal(
        raised,
        step,
        observed="branch-gap",
        requested="resume",
    )


def test_guard_carrier_composes_prefix_and_runs_projection_and_transition_once(
    tmp_path, monkeypatch,
) -> None:
    path = tmp_path / "guard_carrier.py"
    path.write_text("def f(left, right):\n    return left == right\n", encoding="utf-8")
    site = next(SourceFile.from_path(path).functions()).body[0].fragment
    halted = _halt("carrier", pending=(_Pending("pending:carrier"),))
    truth_calls: list[object] = []
    truth = _TruthOperand(
        Complete(PredicateValue(atomic("guard:carrier-truth", []))), truth_calls
    )
    projected = ExitSet(
        (
            halted,
            Completed(atomic("guard:carrier-completed", []), truth),
        )
    )
    carrier = NativeOperationExitCarrierV1.mint(
        site=site,
        operator="equals",
        operands=(_CarrierReceiver(projected), TermValue(2)),
        coordinates=(None, None),
    )
    transition_calls = _transition_truth_spy(monkeypatch)

    step = _step(_OutcomeGuard(carrier))
    machine = _machine(step)
    deferred = machine.resume()

    assert isinstance(deferred, NativeOperationExitCarrierV1)
    assert deferred.demand is carrier.demand
    assert truth_calls == []
    assert transition_calls == []
    outcome = deferred.discharge({})
    assert truth_calls == [machine.instance_coordinate]
    assert truth_calls[0] is machine.instance_coordinate
    assert len(transition_calls) == 1
    assert transition_calls[0].formula == atomic("guard:carrier-truth", [])
    assert isinstance(outcome, ExitSet)
    _assert_halt_identity(outcome.exits[0], halted)
    completed = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert len(completed) == 1
    assert isinstance(completed[0].value, GuardedValue)
    assert isinstance(completed[0].value.when_true, YieldEffect)
    assert isinstance(completed[0].value.when_false, YieldEffect)


def test_projected_truth_exitset_composes_a_branch_carrier_without_duplication(
    tmp_path, monkeypatch,
) -> None:
    path = tmp_path / "projected_truth_carrier.py"
    path.write_text("def f(left, right):\n    return left == right\n", encoding="utf-8")
    site = next(SourceFile.from_path(path).functions()).body[0].fragment
    branch_carrier = NativeOperationExitCarrierV1.mint(
        site=site,
        operator="equals",
        operands=(
            _CarrierReceiver(ExitSet.completed(TermValue(9))),
            TermValue(2),
        ),
        coordinates=(None, None),
    )
    truth_halted = _halt("projected-truth", pending=(_Pending("pending:truth"),))
    projected_truth = ExitSet(
        (
            truth_halted,
            Completed(
                atomic("guard:projected-truth", []),
                TrueBoolLiteralSugar(site="guard:projected:true"),
            ),
        )
    )
    projection_calls: list[object] = []
    operand = _TruthOperand(projected_truth, projection_calls)
    original_prefix_guard = atomic("guard:original-prefix", [])
    original_prefix = ExitSet((Completed(original_prefix_guard, operand),))
    step = IfStepV1(
        _OutcomeGuard(original_prefix),
        (
            AssignStepV1(
                "answer", _OutcomeGuard(branch_carrier), "assign:branch-carrier"
            ),
            YieldStepV1(IntLiteralSugar(1, site="yield:branch-carrier")),
        ),
        (),
        "if:projected-truth-carrier",
    )
    transition_calls = _transition_truth_spy(monkeypatch)
    machine = _machine(step)

    deferred = machine.resume()

    assert isinstance(deferred, NativeOperationExitCarrierV1)
    assert deferred.demand is branch_carrier.demand
    assert projection_calls == [machine.instance_coordinate]
    assert projection_calls[0] is machine.instance_coordinate
    assert transition_calls == [projected_truth.exits[1].value]
    outcome = deferred.discharge({})
    assert projection_calls == [machine.instance_coordinate]
    assert transition_calls == [projected_truth.exits[1].value]
    assert isinstance(outcome, ExitSet)
    nested_halted = outcome.exits[0]
    assert isinstance(nested_halted, Halted)
    assert nested_halted.guard == and_([original_prefix_guard, truth_halted.guard])
    assert nested_halted.effect is truth_halted.effect
    assert nested_halted.state is truth_halted.state
    assert nested_halted.faces == truth_halted.faces
    assert nested_halted.faces is not truth_halted.faces
    assert len(nested_halted.faces) == len(truth_halted.faces) == 1
    assert next(iter(nested_halted.faces)) is next(iter(truth_halted.faces))
    assert nested_halted.pending_contracts is truth_halted.pending_contracts
    completed = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert completed[0].value.machine.cursor == 2
