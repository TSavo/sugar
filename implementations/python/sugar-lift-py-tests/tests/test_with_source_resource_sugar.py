"""Disposition routing twins for source-derived resource managers."""

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    EffectMatcher,
    ReturnTruthinessDispositionV1,
    Suppresses,
)
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
from sugar_lift_py_tests.floor import (
    BlockValue,
    ObjectValue,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, not_
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import true_guard
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.resource_coord_sugar import (
    ExitTracebackRefSugar,
    ExitTypeRefSugar,
    ExitValueRefSugar,
    ManagerRefSugar,
)
from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
    WithSourceResourceSugar,
)

from frame_fresh import FRAME_FRESH


class _FixedSugar(Sugar):
    # A canned statement binds nothing before its halts: the block's prefix
    # is their record.
    halts_at_statement_head = True

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
        return ExitSet.completed(SimpleNamespace(enter_value=self.enter_value))

    def exit_outcome_for(self, entered, ctx=None):
        assert entered.enter_value == self.enter_value
        del ctx
        self.exit_calls += 1
        return ExitSet.completed(self.exit_value)


def _protocol_calls():
    enter_definition = SourceFragmentCoordinateV1("blake3-512:" + "e" * 128, 1, 0, 1, 1)
    exit_definition = SourceFragmentCoordinateV1("blake3-512:" + "x" * 128, 2, 0, 2, 1)
    enter = MethodCallSugar(
        receiver=ManagerRefSugar(slot_id="manager-slot", site=None),
        name="__enter__",
        args=(),
        native_definition_coordinate=enter_definition,
        site=None,
    )
    exit_ = MethodCallSugar(
        receiver=ManagerRefSugar(slot_id="manager-slot", site=None),
        name="__exit__",
        args=(
            ExitTypeRefSugar(face_id="exit-face", site=None),
            ExitValueRefSugar(face_id="exit-face", site=None),
            ExitTracebackRefSugar(face_id="exit-face", site=None),
        ),
        native_definition_coordinate=exit_definition,
        site=None,
    )
    return enter, exit_, enter_definition, exit_definition


def _source_resource(**kwargs):
    enter, exit_, enter_definition, exit_definition = _protocol_calls()
    return WithSourceResourceSugar(
        enter=enter,
        exit=exit_,
        enter_definition=enter_definition,
        exit_definition=exit_definition,
        **kwargs,
    )


def _truthiness_resource(*, exit_value, body, enter_value=TermValue(2), slot=None):
    summary = SimpleNamespace(
        semantics=SimpleNamespace(
            exit=SimpleNamespace(disposition=ReturnTruthinessDispositionV1())
        )
    )
    protocol = _CompletedProtocol(enter_value=enter_value, exit_value=exit_value)
    return (
        _source_resource(
            manager=_FixedSugar(ExitSet.completed(TermValue(1))),
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
    from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

    disposition = Suppresses(EffectMatcher(kind="raise", name="ValueError"))
    summary = SimpleNamespace(
        semantics=SimpleNamespace(exit=SimpleNamespace(disposition=disposition))
    )
    protocol = _CompletedProtocol()
    _, mro = _builtin_exception_identity("ValueError")
    sugar = _source_resource(
        manager=_FixedSugar(ExitSet.completed(TermValue(1))),
        protocol=protocol,
        summary=summary,
        body=(
            _FixedSugar(
                ExitSet.halted(
                    RaiseEffect.for_builtin(
                        "ValueError",
                        occurrence="resource.py:4:8",
                        exception_type_mro=mro,
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
    effect = RaiseEffect.for_builtin("ValueError", occurrence="resource.py:4:8")
    sugar, protocol = _truthiness_resource(
        exit_value=TermValue(True), body=(_FixedSugar(ExitSet.halted(effect)),)
    )

    exits = sugar.desugar().exits

    assert not any(isinstance(face, Halted) for face in exits)
    assert any(isinstance(face, Completed) for face in exits)
    assert protocol.exit_calls == 1


def test_source_false_exit_passes_the_exact_halted_edge_through():
    effect = RaiseEffect.for_builtin("ValueError", occurrence="resource.py:4:8")
    sugar, protocol = _truthiness_resource(
        exit_value=TermValue(False), body=(_FixedSugar(ExitSet.halted(effect)),)
    )

    exits = sugar.desugar().exits

    halted = [face for face in exits if isinstance(face, Halted)]
    assert len(halted) == 1
    assert halted[0].effect == effect
    assert protocol.exit_calls == 1


def test_source_undecided_exit_keeps_both_suppression_faces():
    effect = RaiseEffect.for_builtin("ValueError", occurrence="resource.py:4:8")
    result = SymbolicValue(ctor("fixture:undecided-exit", ()))
    sugar, _ = _truthiness_resource(
        exit_value=result, body=(_FixedSugar(ExitSet.halted(effect)),)
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
        exit_value=TermValue(False), body=(_FixedSugar(ExitSet.completed(returned)),)
    )

    exits = sugar.desugar().exits

    assert exits
    assert protocol.exit_calls == 1


@pytest.mark.parametrize(
    ("body_outcome", "exit_truth", "surviving_face"),
    [
        (
            ExitSet.completed(BlockValue((), can_fall_through=True)),
            TermValue(True),
            Completed,
        ),
        (
            ExitSet.completed(
                BlockValue((ReturnValue(TermValue("early")),), can_fall_through=False)
            ),
            TermValue(True),
            Completed,
        ),
        (
            ExitSet.halted(
                RaiseEffect.for_builtin("ValueError", occurrence="resource.py:8:8")
            ),
            TermValue(False),
            Halted,
        ),
    ],
    ids=("completed", "returned", "halted"),
)
def test_source_exit_runs_over_completed_returned_and_halted_faces(
    body_outcome, exit_truth, surviving_face
):
    """Exit truth is consulted for all faces but changes only an incoming raise."""
    sugar, protocol = _truthiness_resource(
        exit_value=exit_truth,
        body=(_FixedSugar(body_outcome),),
    )

    exits = sugar.desugar().exits

    assert protocol.exit_calls == 1
    assert any(isinstance(face, surviving_face) for face in exits)


@pytest.mark.parametrize("action", ["break", "continue"])
def test_source_truthy_exit_runs_but_cannot_suppress_loop_transfer(action):
    loop = LoopControlEffect(
        action,
        "blake3-512:" + "1" * 128,
        "blake3-512:" + "2" * 128,
    )
    sugar, protocol = _truthiness_resource(
        exit_value=TermValue(True), body=(_FixedSugar(ExitSet.halted(loop)),)
    )

    exits = sugar.desugar().exits

    halted = [face for face in exits if isinstance(face, Halted)]
    assert len(halted) == 1
    assert halted[0].effect == loop
    assert protocol.exit_calls == 1


def _returns_of(record):
    from sugar_lift_py_tests.floor import GuardedReturn

    return tuple(
        entry
        for entry in record.entries
        if isinstance(entry, (ReturnValue, GuardedReturn))
    )


def test_a_suppressed_halt_goes_on_without_the_dead_return_its_record_holds():
    """``with S(): if c: return 1; raise E`` then ``return 3``, ``S.__exit__``
    returning True: one return per record, 1 and 3.

    The raise leaves after the guarded ``return 1``: its record holds that
    return, dead on the raise's arm (the reducer guards the raise by the
    return's fall-through, and ``return 1`` leaves as its own face). The
    ``with`` suppresses the raise and goes on from the record a continuation
    after a halt starts from (``resumed``): without that return, with no
    fall-through guard or transform of the halted block. Carrying the halt's
    record as it was put ``return 1`` beside ``return 3`` on one record (and
    minted the ``return 1`` face a second time)."""
    from sugar_lift_py_tests.floor import GuardedReturn
    from sugar_lift_py_tests.ir import atomic
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _ReducedBlock,
        reduce_block_to_exitset,
    )

    c = atomic("test.c", [])

    def under_not_c(entries):
        # What the ``if`` guards every later statement by: its fall-through.
        return tuple(
            GuardedReturn((not_(c),), entry.value)
            if isinstance(entry, ReturnValue)
            else entry
            for entry in entries
        )

    # ``if c: return 1``: the record goes on under ``not c``, holding the
    # guarded return.
    after_if = _FixedSugar(
        ExitSet.completed(
            _ReducedBlock(
                (GuardedReturn((c,), TermValue(1)),),
                True,
                (not_(c),),
                (under_not_c,),
            )
        )
    )
    raise_e = _FixedSugar(
        ExitSet.halted(
            RaiseEffect.for_builtin("ValueError", occurrence="resource.py:6:8")
        )
    )
    sugar, protocol = _truthiness_resource(
        exit_value=TermValue(True), body=(after_if, raise_e)
    )
    return_3 = _FixedSugar(
        ExitSet.completed(_ReducedBlock((ReturnValue(TermValue(3)),), False, ()))
    )

    exits = reduce_block_to_exitset((sugar, return_3), None)

    assert protocol.exit_calls == 1
    assert not any(isinstance(face, Halted) for face in exits.exits), exits
    records = [face.value for face in exits.exits]
    for record in records:
        assert not record.can_fall_through, record
        assert len(_returns_of(record)) == 1, record.entries
    values = sorted(_returns_of(record)[0].value.value for record in records)
    assert values == [1, 3], values


def test_enter_as_binding_carries_object_occurrence_identity():
    entered = ObjectValue(
        "RenamedResource",
        (),
        identity="object-occurrence-cid",
        allocation=FRAME_FRESH,
    )
    sugar, _ = _truthiness_resource(
        exit_value=TermValue(False),
        enter_value=entered,
        body=(_FixedSugar(ExitSet.completed(BlockValue((), can_fall_through=True))),),
        slot="enter-slot",
    )

    rendered = repr(sugar.desugar())

    assert "enter_result_value" in rendered
    assert "py.object.identity" in rendered
    assert "object-occurrence-cid" in rendered
