"""Test-first law for linear and nonlinear generator value consumers.

Legacy Complete/raw values remain linear: Yield and Return keep their direct
result shapes.  Only Incomplete/ExitSet outcomes enter the exit algebra;
Halted faces bypass consumers and Completed faces alone transition the live
machine.  Every producer reduction occurs exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import sugar_lift_py_tests.generator_construction as generator_module
from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.effect import (
    DynamicTypeOperandRuntimeEffect,
    RaiseEffect,
    runtime_effect_evidence_from_terms,
)
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.generator_construction import (
    AssignStepV1,
    GeneratorAssignBindingV1,
    GeneratorConstructionV1,
    GeneratorTerminationV1,
    GeneratorTransitionGapV1,
    OpaqueStepV1,
    ReturnStepV1,
    YieldEffect,
    YieldStepV1,
)
from sugar_lift_py_tests.ir import and_, atomic, ctor, make_var, not_
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted, Incomplete
from sugar_lift_py_tests.outcome.exit_set import partition
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_source_tree.nodes import Call
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _OutcomeValue(ConstructedTermSugar):
    outcome: object
    reductions: list[str] = field(compare=False, repr=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        self.reductions.append("value")
        return self.outcome

    def to_term(self, *, owner: str):
        del owner
        return TermValue("generator-value").to_term(owner="generator value")


@dataclass(frozen=True)
class _Pending:
    candidate_cid: str


@dataclass(frozen=True)
class _RefusingValue(ConstructedTermSugar):
    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        raise SugarNotWritten(
            blame="refusing-value",
            owner="_RefusingValue",
            observed="linear-refusal",
            requested="constructed value",
            fix="implement the refusing value",
        )

    def to_term(self, *, owner: str):
        del owner
        return TermValue("refusing-value").to_term(owner="refusing value")


@dataclass(frozen=True)
class _CarrierReceiver(FloorValue):
    outcome: ExitSet

    def equals(self, other, site):
        del other, site
        return self.outcome

    def to_term(self, *, owner: str):
        del owner
        return TermValue("carrier-receiver").to_term(owner="carrier receiver")


def _machine(steps):
    return GeneratorConstructionV1.allocate(
        allocation_coordinate="call:generator-value-exitset",
        frame_coordinate="frame:generator-value-exitset",
        binding_state=(),
        steps=steps,
    )


def _mixed_faces():
    left_guard = atomic("generator.value.halted.left", [])
    completed_guard = atomic("generator.value.completed", [])
    right_guard = atomic("generator.value.halted.right", [])
    left_face, completed_left_face = partition("generator-value-left")
    completed_right_face, right_face = partition("generator-value-right")
    pending = (_Pending("pending:halted-left"),)
    halted_left = Halted(
        left_guard,
        RaiseEffect(exception_name="LeftError", occurrence="value:halted:left"),
        state=object(),
        faces=frozenset({left_face}),
        pending_contracts=pending,
    )
    completed = Completed(
        completed_guard,
        TermValue(11),
        frozenset({completed_left_face, completed_right_face}),
        (),
    )
    halted_right = Halted(
        right_guard,
        RaiseEffect(exception_name="RightError", occurrence="value:halted:right"),
        state=object(),
        faces=frozenset({right_face}),
        pending_contracts=(),
    )
    return ExitSet((halted_left, completed, halted_right)), (
        halted_left,
        completed,
        halted_right,
    )


def _assert_mixed_prefix(outcome, original):
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 3
    assert outcome.exits[0] is original[0]
    assert isinstance(outcome.exits[1], Completed)
    assert outcome.exits[1].guard is original[1].guard
    assert outcome.exits[2] is original[2]
    for actual, expected in (
        (outcome.exits[0], original[0]),
        (outcome.exits[2], original[2]),
    ):
        assert actual.effect is expected.effect
        assert actual.state is expected.state
        assert actual.guard is expected.guard
        assert actual.faces is expected.faces
        assert actual.pending_contracts is expected.pending_contracts


def _install_transition_spy(monkeypatch, consumer: str):
    calls: list[tuple] = []
    if consumer == "assign":
        original = GeneratorAssignBindingV1

        def binding(*args, **kwargs):
            calls.append(args)
            return original(*args, **kwargs)

        monkeypatch.setattr(generator_module, "GeneratorAssignBindingV1", binding)
    elif consumer == "return":
        original = GeneratorTerminationV1

        def termination(*args, **kwargs):
            calls.append(args)
            return original(*args, **kwargs)

        monkeypatch.setattr(generator_module, "GeneratorTerminationV1", termination)
    else:
        original = YieldEffect

        def yielded(*args, **kwargs):
            calls.append(args)
            return original(*args, **kwargs)

        monkeypatch.setattr(generator_module, "YieldEffect", yielded)
    return calls


def test_assign_sequences_one_completed_face_and_bypasses_two_halted_faces(
    monkeypatch,
) -> None:
    exits, original = _mixed_faces()
    reductions: list[str] = []
    value = _OutcomeValue(exits, reductions)
    next_reductions: list[str] = []
    next_value = _OutcomeValue(Complete(TermValue(99)), next_reductions)
    continuation_calls = _install_transition_spy(monkeypatch, "assign")

    outcome = _machine(
        (
            AssignStepV1("saved", value, "assign:fragment"),
            YieldStepV1(next_value),
        )
    ).resume()

    assert reductions == ["value"]
    assert next_reductions == ["value"]
    assert len(continuation_calls) == 1
    _assert_mixed_prefix(outcome, original)
    completed = outcome.exits[1]
    assert isinstance(completed.value, YieldEffect)
    assert completed.value.value == TermValue(99)
    binding = completed.value.machine.binding_state[-1]
    assert isinstance(binding, GeneratorAssignBindingV1)
    assert binding.name == "saved"
    assert binding.value is original[1].value
    assert completed.value.machine.cursor == 2


@pytest.mark.parametrize("consumer", ("return", "yield"))
def test_return_and_yield_sequence_one_completed_face_and_two_halts(
    monkeypatch, consumer: str,
) -> None:
    exits, original = _mixed_faces()
    reductions: list[str] = []
    value = _OutcomeValue(exits, reductions)
    step = ReturnStepV1(value) if consumer == "return" else YieldStepV1(value)
    continuation_calls = _install_transition_spy(monkeypatch, consumer)

    outcome = _machine((step,)).resume()

    assert reductions == ["value"]
    assert len(continuation_calls) == 1
    _assert_mixed_prefix(outcome, original)
    completed = outcome.exits[1]
    if consumer == "return":
        assert isinstance(completed.value, GeneratorTerminationV1)
        assert completed.value.return_value is original[1].value
    else:
        assert isinstance(completed.value, YieldEffect)
        assert completed.value.value is original[1].value


def test_synthetic_all_halted_assign_is_unchanged_and_runs_no_continuation(
    tmp_path,
) -> None:
    source = (
        "import re\n"
        "from re import RegexFlag\n"
        "def option_undo():\n"
        "    undo = isinstance(re.I, RegexFlag)\n"
    )
    path = tmp_path / "option_undo.py"
    path.write_text(source, encoding="utf-8")
    tree = SourceFile.from_path(path)
    occurrence = next(node.fragment for node in tree.nodes() if isinstance(node, Call))
    membership_guard = atomic("option.contains", [])
    equality_guard = atomic("option.equals", [])
    membership_true, membership_false = partition("option-membership")
    equality_true, equality_false = partition("option-equality")
    dynamic_operation = ctor(
        "adt.is_python_type", (make_var("re.I"), make_var("RegexFlag"))
    )
    dynamic = DynamicTypeOperandRuntimeEffect(
        "isinstance(re.I, RegexFlag) requires Python runtime type resolution",
        **runtime_effect_evidence_from_terms(
            dynamic_operation, make_var("RegexFlag"), occurrence
        ),
    )
    arms = (
        Halted(
            membership_guard,
            RaiseEffect(exception_name="TypeError", occurrence="contains"),
            None,
            frozenset({membership_true}),
            (),
        ),
        Halted(
            and_((not_(membership_guard), equality_guard)),
            RaiseEffect(exception_name="TypeError", occurrence="equals"),
            None,
            frozenset({membership_false, equality_true}),
            (),
        ),
        Halted(
            and_((not_(membership_guard), not_(equality_guard))),
            dynamic,
            _ReducedBlock((), True, ()),
            frozenset({membership_false, equality_false}),
            (),
        ),
    )
    reductions: list[str] = []
    continuation_reductions: list[str] = []
    value = _OutcomeValue(ExitSet(arms), reductions)
    next_value = _OutcomeValue(Complete(TermValue(99)), continuation_reductions)
    machine = _machine(
        (
            AssignStepV1("undo", value, "config.py:512"),
            YieldStepV1(next_value),
        )
    )

    outcome = machine.resume()

    assert reductions == ["value"]
    assert continuation_reductions == []
    assert isinstance(outcome, ExitSet)
    assert outcome.exits == arms
    assert all(actual is expected for actual, expected in zip(outcome.exits, arms))
    assert all(face.state is expected.state for face, expected in zip(outcome.exits, arms))
    assert machine.cursor == 0
    assert not machine.binding_state


@pytest.mark.parametrize("consumer", ("assign", "return", "yield"))
def test_incomplete_value_becomes_one_halted_face_without_advancing(consumer: str) -> None:
    effect = RaiseEffect(exception_name="ValueError", occurrence="incomplete:value")
    reductions: list[str] = []
    value = _OutcomeValue(Incomplete(effect), reductions)
    if consumer == "assign":
        step = AssignStepV1("saved", value, "assign:incomplete")
    elif consumer == "return":
        step = ReturnStepV1(value)
    else:
        step = YieldStepV1(value)
    machine = _machine((step,))

    outcome = machine.resume()

    assert reductions == ["value"]
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    assert isinstance(outcome.exits[0], Halted)
    assert outcome.exits[0].effect is effect
    assert outcome.exits[0].state is None
    assert machine.cursor == 0


@pytest.mark.parametrize("consumer", ("assign", "return", "yield"))
def test_nonlinear_continuation_gap_stays_typed_loud(
    monkeypatch, consumer: str
) -> None:
    exits, _ = _mixed_faces()
    reductions: list[str] = []
    value = _OutcomeValue(exits, reductions)
    if consumer == "assign":
        steps = (
            AssignStepV1("saved", value, "assign:bad-tail"),
            OpaqueStepV1("unsupported-tail"),
        )
        blamed_step = steps[0]
    elif consumer == "return":
        blamed_step = ReturnStepV1(value)
        steps = (blamed_step,)
        monkeypatch.setattr(
            generator_module,
            "GeneratorTerminationV1",
            lambda *args, **kwargs: GeneratorTransitionGapV1(
                "GeneratorConstructionV1.transition",
                "unsupported-tail",
                "resume",
            ),
        )
    else:
        blamed_step = YieldStepV1(value)
        steps = (blamed_step,)
        monkeypatch.setattr(
            generator_module,
            "YieldEffect",
            lambda *args, **kwargs: GeneratorTransitionGapV1(
                "GeneratorConstructionV1.transition",
                "unsupported-tail",
                "resume",
            ),
        )

    with pytest.raises(SugarNotWritten) as raised:
        _machine(steps).resume()

    assert reductions == ["value"]
    assert raised.value.owner == "GeneratorConstructionV1.transition"
    assert raised.value.blame is blamed_step
    assert raised.value.observed == "unsupported-tail"
    assert raised.value.requested == "resume"
    assert raised.value.fix == (
        "implement that next transition before deferred normalization"
    )


def _carrier(tmp_path, *, mixed: bool = False):
    path = tmp_path / "carrier.py"
    path.write_text("def f(left, right):\n    return left == right\n", encoding="utf-8")
    site = next(SourceFile.from_path(path).functions()).body[0].fragment
    halted = None
    completed_value = None
    operands = (TermValue(1), TermValue(2))
    if mixed:
        halted_face, completed_face = partition("carrier-discharge")
        halted = Halted(
            atomic("carrier:halted", []),
            RaiseEffect(exception_name="CarrierError", occurrence="carrier:halted"),
            state=object(),
            faces=frozenset({halted_face}),
            pending_contracts=(_Pending("pending:carrier-halted"),),
        )
        completed_value = TermValue(3)
        projected = ExitSet(
            (
                halted,
                Completed(
                    atomic("carrier:completed", []),
                    completed_value,
                    frozenset({completed_face}),
                    (),
                ),
            )
        )
        operands = (_CarrierReceiver(projected), TermValue(2))
    carrier = NativeOperationExitCarrierV1.mint(
        site=site,
        operator="equals",
        operands=operands,
        coordinates=(None, None),
    )
    existing_calls: list[object] = []

    def existing(value):
        existing_calls.append(value)
        return Complete(value)

    guard = atomic("carrier:existing-guard", [])
    return (
        carrier.and_then(existing).guarded(guard),
        existing,
        existing_calls,
        guard,
        halted,
        completed_value,
    )


@pytest.mark.parametrize("consumer", ("assign", "return", "yield"))
def test_native_exit_carrier_preserves_identity_and_appends_one_continuation(
    tmp_path, monkeypatch, consumer: str
) -> None:
    carrier, existing, existing_calls, guard, halted, completed_value = _carrier(
        tmp_path, mixed=True
    )
    reductions: list[str] = []
    value = _OutcomeValue(carrier, reductions)
    if consumer == "assign":
        step = AssignStepV1("saved", value, "assign:carrier")
    elif consumer == "return":
        step = ReturnStepV1(value)
    else:
        step = YieldStepV1(value)
    continuation_calls = _install_transition_spy(monkeypatch, consumer)

    outcome = _machine((step,)).resume()

    assert reductions == ["value"]
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand is carrier.demand
    assert outcome.operands is carrier.operands
    assert outcome.coordinates is carrier.coordinates
    assert outcome.guards == carrier.guards == (guard,)
    assert outcome.pre_effect_state is carrier.pre_effect_state
    assert outcome.continuations[:-1] == carrier.continuations == (existing,)
    assert len(outcome.continuations) == len(carrier.continuations) + 1
    assert existing_calls == []
    assert continuation_calls == []

    discharged = outcome.discharge({})
    assert isinstance(discharged, ExitSet)
    assert len(existing_calls) == 1
    assert existing_calls[0] is completed_value
    assert len(continuation_calls) == 1
    assert len(discharged.exits) == 2
    halted_after = discharged.exits[0]
    assert isinstance(halted_after, Halted)
    assert halted is not None
    assert halted_after.effect is halted.effect
    assert halted_after.state is halted.state
    assert halted_after.faces is halted.faces
    assert halted_after.pending_contracts is halted.pending_contracts
    completed = discharged.exits[1]
    assert isinstance(completed, Completed)
    if consumer == "return":
        assert isinstance(completed.value, GeneratorTerminationV1)
        assert completed.value.return_value is not None
    elif consumer == "yield":
        assert isinstance(completed.value, YieldEffect)
    else:
        assert isinstance(completed.value, GeneratorTerminationV1)
        binding = completed.value.binding_state[-1]
        assert isinstance(binding, GeneratorAssignBindingV1)
        assert binding.name == "saved"


@pytest.mark.parametrize("consumer", ("assign", "return", "yield"))
def test_native_exit_carrier_gap_callback_raises_exact_transition_refusal(
    tmp_path, monkeypatch, consumer: str,
) -> None:
    carrier, _, _, _, _, _ = _carrier(tmp_path)
    reductions: list[str] = []
    value = _OutcomeValue(carrier, reductions)
    if consumer == "assign":
        steps = (
            AssignStepV1("saved", value, "assign:carrier-gap"),
            OpaqueStepV1("carrier-tail-gap"),
        )
        blamed_step = steps[0]
    elif consumer == "return":
        blamed_step = ReturnStepV1(value)
        steps = (blamed_step,)
        monkeypatch.setattr(
            generator_module,
            "GeneratorTerminationV1",
            lambda *args, **kwargs: GeneratorTransitionGapV1(
                "GeneratorConstructionV1.transition",
                "carrier-tail-gap",
                "resume",
            ),
        )
    else:
        blamed_step = YieldStepV1(value)
        steps = (blamed_step,)
        monkeypatch.setattr(
            generator_module,
            "YieldEffect",
            lambda *args, **kwargs: GeneratorTransitionGapV1(
                "GeneratorConstructionV1.transition",
                "carrier-tail-gap",
                "resume",
            ),
        )
    deferred = _machine(steps).resume()

    assert reductions == ["value"]
    assert isinstance(deferred, NativeOperationExitCarrierV1)
    with pytest.raises(SugarNotWritten) as raised:
        deferred.discharge({})
    assert raised.value.owner == "GeneratorConstructionV1.transition"
    assert raised.value.blame is blamed_step
    assert raised.value.observed == "carrier-tail-gap"
    assert raised.value.requested == "resume"
    assert raised.value.fix == (
        "implement that next transition before deferred normalization"
    )


def test_ordinary_complete_yield_retains_direct_yield_effect() -> None:
    reductions: list[str] = []
    value = _OutcomeValue(Complete(TermValue(7)), reductions)

    outcome = _machine((YieldStepV1(value),)).resume()

    assert reductions == ["value"]
    assert isinstance(outcome, YieldEffect)
    assert outcome.value == TermValue(7)


def test_ordinary_complete_return_retains_direct_termination() -> None:
    reductions: list[str] = []
    value = _OutcomeValue(Complete(TermValue(7)), reductions)

    outcome = _machine((ReturnStepV1(value),)).resume()

    assert reductions == ["value"]
    assert isinstance(outcome, GeneratorTerminationV1)
    assert outcome.return_value == TermValue(7)


def test_reduce_value_keeps_none_and_non_sugar_raw() -> None:
    machine = _machine(())
    raw = TermValue(7)

    assert machine._reduce_value(None, "linear") is None
    assert machine._reduce_value(raw, "linear") is raw


def test_reduce_value_keeps_sugar_not_written_as_direct_transition_gap() -> None:
    machine = _machine(())

    outcome = machine._reduce_value(_RefusingValue(), "linear-request")

    assert isinstance(outcome, GeneratorTransitionGapV1)
    assert outcome.owner == "GeneratorConstructionV1.transition"
    assert outcome.observed == "linear-refusal"
    assert outcome.requested == "linear-request"
