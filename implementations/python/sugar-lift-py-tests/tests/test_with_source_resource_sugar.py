"""Disposition routing twins for source-derived resource managers."""

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    EffectMatcher,
    ReturnTruthinessDispositionV1,
    Suppresses,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
from sugar_lift_py_tests.floor import BlockValue, ObjectValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, not_
from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
from sugar_lift_py_tests.outcome.exit_set import true_guard
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
    WithSourceResourceSugar,
)


class _FixedSugar(Sugar):
    def __init__(self, outcome):
        self.outcome = outcome

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


class _CompletedProtocol:
    def __init__(self, *, enter_value=TermValue(2), exit_value=None):
        self.enter_calls = 0
        self.exit_calls = 0
        self.enter_value = enter_value
        self.exit_value = exit_value or BlockValue((), can_fall_through=True)

    def enter_resource_outcome(self, ctx=None):
        del ctx
        self.enter_calls += 1
        return Complete(SimpleNamespace(enter_value=self.enter_value))

    def exit_outcome_for(self, entered, ctx=None):
        assert entered.enter_value == self.enter_value
        del ctx
        self.exit_calls += 1
        return Complete(self.exit_value)


def _truthiness_resource(*, exit_value, body, enter_value=TermValue(2), slot=None):
    summary = SimpleNamespace(
        semantics=SimpleNamespace(
            exit=SimpleNamespace(disposition=ReturnTruthinessDispositionV1())
        )
    )
    protocol = _CompletedProtocol(enter_value=enter_value, exit_value=exit_value)
    return (
        WithSourceResourceSugar(
            manager=_FixedSugar(Complete(TermValue(1))),
            protocol=protocol,
            summary=summary,
            body=body,
            manager_slot_id="manager-slot",
            enter_slot_id=slot,
            exit_face_id="exit-face",
            site="resource.py:3:4",
        ),
        protocol,
    )


def test_summary_suppresses_disposition_consumes_matching_body_halt():
    disposition = Suppresses(EffectMatcher(kind="raise", name="ValueError"))
    summary = SimpleNamespace(
        semantics=SimpleNamespace(exit=SimpleNamespace(disposition=disposition))
    )
    protocol = _CompletedProtocol()
    sugar = WithSourceResourceSugar(
        manager=_FixedSugar(Complete(TermValue(1))),
        protocol=protocol,
        summary=summary,
        body=(
            _FixedSugar(
                Incomplete(
                    RaiseEffect(
                        exception_name="ValueError", occurrence="resource.py:4:8"
                    )
                )
            ),
        ),
        manager_slot_id="manager-slot",
        enter_slot_id=None,
        exit_face_id="exit-face",
        site="resource.py:3:4",
    )

    exits = sugar.desugar().exits

    assert exits
    assert not any(
        isinstance(face, Halted)
        and getattr(face.effect, "exception_name", None) == "ValueError"
        for face in exits
    )
    assert protocol.enter_calls == 1
    assert protocol.exit_calls == 1


def test_source_true_exit_consumes_the_halted_edge():
    effect = RaiseEffect(exception_name="ValueError", occurrence="resource.py:4:8")
    sugar, protocol = _truthiness_resource(
        exit_value=TermValue(True), body=(_FixedSugar(Incomplete(effect)),)
    )

    exits = sugar.desugar().exits

    assert not any(isinstance(face, Halted) for face in exits)
    assert any(isinstance(face, Completed) for face in exits)
    assert protocol.exit_calls == 1


def test_source_false_exit_passes_the_exact_halted_edge_through():
    effect = RaiseEffect(exception_name="ValueError", occurrence="resource.py:4:8")
    sugar, protocol = _truthiness_resource(
        exit_value=TermValue(False), body=(_FixedSugar(Incomplete(effect)),)
    )

    exits = sugar.desugar().exits

    halted = [face for face in exits if isinstance(face, Halted)]
    assert len(halted) == 1
    assert halted[0].effect == effect
    assert protocol.exit_calls == 1


def test_source_undecided_exit_keeps_both_suppression_faces():
    effect = RaiseEffect(exception_name="ValueError", occurrence="resource.py:4:8")
    result = SymbolicValue(ctor("fixture:undecided-exit", ()))
    sugar, _ = _truthiness_resource(
        exit_value=result, body=(_FixedSugar(Incomplete(effect)),)
    )

    exits = sugar.desugar().exits

    assert len(exits) >= 2
    assert any(isinstance(face, Completed) for face in exits)
    halted = next(face for face in exits if isinstance(face, Halted))
    assert halted.effect == effect
    assert any(
        isinstance(face, Completed) and halted.guard == not_(face.guard)
        for face in exits
    )


def test_source_exit_runs_on_early_return_face():
    from sugar_lift_py_tests.floor import ReturnValue

    returned = BlockValue((ReturnValue(TermValue("early")),), can_fall_through=False)
    sugar, protocol = _truthiness_resource(
        exit_value=TermValue(False), body=(_FixedSugar(Complete(returned)),)
    )

    exits = sugar.desugar().exits

    assert exits
    assert protocol.exit_calls == 1


@pytest.mark.parametrize("action", ["break", "continue"])
def test_source_truthy_exit_runs_but_cannot_suppress_loop_transfer(action):
    loop = LoopControlEffect(
        action,
        "blake3-512:" + "1" * 128,
        "blake3-512:" + "2" * 128,
    )
    sugar, protocol = _truthiness_resource(
        exit_value=TermValue(True), body=(_FixedSugar(Incomplete(loop)),)
    )

    exits = sugar.desugar().exits

    halted = [face for face in exits if isinstance(face, Halted)]
    assert len(halted) == 1
    assert halted[0].effect == loop
    assert protocol.exit_calls == 1


def test_enter_as_binding_carries_object_occurrence_identity():
    entered = ObjectValue("RenamedResource", (), identity="object-occurrence-cid")
    sugar, _ = _truthiness_resource(
        exit_value=TermValue(False),
        enter_value=entered,
        body=(_FixedSugar(Complete(BlockValue((), can_fall_through=True))),),
        slot="enter-slot",
    )

    rendered = repr(sugar.desugar())

    assert "enter_result_value" in rendered
    assert "py.object.identity" in rendered
    assert "object-occurrence-cid" in rendered
