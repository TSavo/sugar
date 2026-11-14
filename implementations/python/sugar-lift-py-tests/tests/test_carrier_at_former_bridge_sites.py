"""A deferred native-operation carrier at every former ``outcome_to_exitset`` site.

#7967 deleted the bridge whose named construction panic caught an undischarged
``NativeOperationExitCarrierV1`` reaching a position that needs an ``ExitSet``.
Each site now either composes the carrier through its own ``and_then`` /
``after_discharge`` or refuses it by name through ``_require_exit_set`` under
the site's own owner. None may fail on a missing attribute (#7825).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
)
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import PrimitiveSort, atomic, make_var, str_const
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import partition
from sugar_lift_py_tests.sugar.binding_projection import GuardedProjection
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.binding_state import BranchResultSlot
from sugar_source_tree.tree import SourceFile


# --- one deferred carrier --------------------------------------------------


def _site():
    source = "def operation(left, right):\n    return left + right\n"
    tree = SourceFile(
        (source, "carrier_bridge_sites.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(tree.functions()).fragment


def _coordinate(name: str, ordinal: int) -> FormalParameterCoordinateV1:
    source_cid = "blake3-512:" + "b" * 128
    owner = SourceFragmentCoordinateV1(source_cid, 1, 0, 2, 23)
    return FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=source_cid,
        owner_definition_locus=owner,
        declaration_locus=SourceFragmentCoordinateV1(
            source_cid, 1, 14 + ordinal * 6, 1, 18 + ordinal * 6
        ),
        ordinal=ordinal,
        parameter_kind="positional-or-keyword",
        declared_name=name,
        sort=PrimitiveSort("Value"),
    )


def _carrier(left_name: str = "left", right_name: str = "right", base: int = 0):
    """``left + right`` waiting on its caller's actuals for both formals."""
    left = _coordinate(left_name, base)
    right = _coordinate(right_name, base + 1)
    carrier = NativeOperationExitCarrierV1.mint(
        site=_site(),
        operator="add",
        operands=(
            SymbolicValue(make_var(left_name), left),
            SymbolicValue(make_var(right_name), right),
        ),
        coordinates=(left, right),
    )
    return carrier, left, right


def _refused(excinfo, owner: str) -> None:
    """The refusal names the undischarged demand and the site that read it."""
    assert excinfo.value.info.owner == owner
    assert "undischarged native operation demand" in excinfo.value.info.observed


@dataclass(frozen=True)
class _Answer(Sugar):
    """A sugar whose desugar answers exactly ``answer``."""

    answer: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return self.answer


def _bare(cls, **fields):
    """An instance carrying only the fields the site reads before refusing."""
    instance = object.__new__(cls)
    for name, value in fields.items():
        object.__setattr__(instance, name, value)
    return instance


def _expression(source: str):
    from sugar_source_tree.backend import materialize
    from sugar_source_tree.cpython_adapter import CPythonAstBackend
    from sugar_source_tree.nodes import SourceUnit

    unit = SourceUnit(
        filename="<carrier-bridge-sites>",
        source=source,
        source_cid=blake3_512_of(source.encode("utf-8")),
    )
    return materialize(unit, CPythonAstBackend().expression(unit))


def _raise_effect(name: str) -> RaiseEffect:
    return RaiseEffect(occurrence=AuthenticatedRaiseLocus.of(name))


# --- the one refusal --------------------------------------------------------


def test_and_then_keeps_its_own_owner():
    carrier, _, _ = _carrier()
    prefix = ExitSet.completed(TermValue(0), guard=atomic("test.prefix", []))
    with pytest.raises(ConstructionPanic) as excinfo:
        prefix.and_then(lambda _value: carrier)
    _refused(excinfo, "ExitSet.and_then")


# --- ExitSet.sequence -------------------------------------------------------


def _actuals(*coordinates):
    """Every formal answered in order: 1, 2, 3, ..."""
    return {
        coordinate.coordinate_cid: TermValue(index)
        for index, coordinate in enumerate(coordinates, start=1)
    }


def _testimony(exits):
    """What rides on each arm beside its guard and destination."""
    return [(exit_.faces, exit_.owed) for exit_ in exits.exits]


def test_sequence_composes_a_loop_body_carrier_beneath_its_arm():
    carrier, left, right = _carrier()
    face, _ = partition("carrier-bridge-sites.sequence")
    first = Completed(
        atomic("test.first", []), TermValue(1), frozenset({face}), ("owed.first",)
    )
    second = Completed(atomic("test.second", []), TermValue(2))
    body = ExitSet((first, second))
    tail = ExitSet.completed(TermValue(9))

    composed = body.sequence(lambda value: carrier if value == TermValue(1) else tail)

    assert isinstance(composed, NativeOperationExitCarrierV1)
    actuals = _actuals(left, right)
    exits = composed.discharge(None, actuals)
    discharged = carrier.discharge(None, actuals)
    eager = body.sequence(lambda value: discharged if value == TermValue(1) else tail)
    assert isinstance(exits, ExitSet)
    assert exits == eager
    assert [exit_.value for exit_ in exits.exits] == [TermValue(3), TermValue(9)]
    assert _testimony(exits) == _testimony(eager)
    assert face in exits.exits[0].faces
    assert "owed.first" in exits.exits[0].owed


def test_sequence_composes_a_consume_carrier_beneath_its_halt():
    carrier, left, right = _carrier()
    consumed_guard = atomic("test.consumed", [])
    consumed = Halted(
        consumed_guard, _raise_effect("loop-control"), None, owed=("owed.halt",)
    )
    kept = Halted(atomic("test.kept", []), _raise_effect("other"))
    body = ExitSet((consumed, kept))

    def handler(halt):
        return carrier if halt.guard == consumed_guard else None

    composed = body.sequence(ExitSet.completed, consume=handler)

    assert isinstance(composed, NativeOperationExitCarrierV1)
    actuals = _actuals(left, right)
    exits = composed.discharge(None, actuals)
    discharged = carrier.discharge(None, actuals)
    eager = body.sequence(
        ExitSet.completed,
        consume=lambda halt: discharged if halt.guard == consumed_guard else None,
    )
    assert isinstance(exits, ExitSet)
    assert exits == eager
    assert _testimony(exits) == _testimony(eager)
    assert isinstance(exits.exits[0], Completed)
    assert exits.exits[0].value == TermValue(3)
    assert "owed.halt" in exits.exits[0].owed
    assert exits.exits[-1] == kept


def test_sequence_composes_two_carriers_in_arm_order():
    first, first_left, first_right = _carrier()
    second, second_left, second_right = _carrier("second_left", "second_right", base=2)
    first_guard = atomic("test.first", [])
    second_guard = atomic("test.second", [])
    body = ExitSet(
        (
            Completed(first_guard, TermValue(1)),
            Completed(second_guard, TermValue(2)),
        )
    )

    composed = body.sequence(lambda value: first if value == TermValue(1) else second)

    assert isinstance(composed, NativeOperationExitCarrierV1)
    exits = composed.discharge(
        None, _actuals(first_left, first_right, second_left, second_right)
    )
    assert isinstance(exits, ExitSet)
    assert [exit_.value for exit_ in exits.exits] == [TermValue(3), TermValue(7)]


def test_sequence_refuses_an_uncomposable_step_by_name():
    body = ExitSet.completed(TermValue(0), guard=atomic("test.prefix", []))
    with pytest.raises(ConstructionPanic) as excinfo:
        body.sequence(lambda _value: object())
    assert excinfo.value.info.owner == "ExitSet.sequence"


def test_sequence_refuses_an_uncomposable_consume_by_name():
    body = ExitSet.halted(_raise_effect("uncomposable"))
    with pytest.raises(ConstructionPanic) as excinfo:
        body.sequence(ExitSet.completed, consume=lambda _halt: object())
    assert excinfo.value.info.owner == "ExitSet.sequence"


# --- caller_parameter_contract ---------------------------------------------


def test_compose_prefix_defers_a_carrier_arm():
    carrier, _, _ = _carrier()
    composed = NativeOperationExitCarrierV1.compose_prefix(
        ExitSet.completed(TermValue(0)), lambda _value: carrier
    )
    assert isinstance(composed, NativeOperationExitCarrierV1)
    assert composed.prefix_composition is not None


def test_compose_prefix_refuses_a_non_exit_set_by_name():
    with pytest.raises(ConstructionPanic) as excinfo:
        NativeOperationExitCarrierV1.compose_prefix(
            ExitSet.completed(TermValue(0)), lambda _value: object()
        )
    assert excinfo.value.info.owner == "NativeOperationExitCarrierV1.compose_prefix"


def test_discharge_exitset_step_answering_a_carrier_discharges_it():
    outer, left, right = _carrier()
    inner, inner_left, inner_right = _carrier("inner_left", "inner_right", base=2)
    exits = outer.after_discharge(lambda _projected: inner).discharge(
        None,
        {
            left.coordinate_cid: TermValue(1),
            right.coordinate_cid: TermValue(2),
            inner_left.coordinate_cid: TermValue(3),
            inner_right.coordinate_cid: TermValue(4),
        },
    )
    assert isinstance(exits, ExitSet)
    assert exits.exits[0].value == TermValue(7)


def test_discharge_projector_answering_a_carrier_is_refused_by_name(monkeypatch):
    outer, left, right = _carrier()
    inner, _, _ = _carrier("inner_left", "inner_right", base=2)
    monkeypatch.setitem(
        _NATIVE_OPERATION_PROJECTORS, "add", lambda left, right, site, ctx: inner
    )
    with pytest.raises(ConstructionPanic) as excinfo:
        outer.discharge(
            None,
            {left.coordinate_cid: TermValue(1), right.coordinate_cid: TermValue(2)},
        )
    _refused(excinfo, "NativeOperationExitCarrierV1.discharge")


# --- contract_expression ----------------------------------------------------


def _contract_answering(monkeypatch, answer):
    from sugar_lift_py_tests import contract_expression

    real = contract_expression.materialize

    def materialize(unit, ref):
        node = real(unit, ref)
        monkeypatch.setattr(
            type(node),
            "substitute",
            lambda self, scope: SimpleNamespace(sugar=lambda: _Answer(answer)),
        )
        return node

    monkeypatch.setattr(contract_expression, "materialize", materialize)
    return contract_expression.parse_contract_expression


def test_contract_expression_value_carrier_is_refused_by_name(monkeypatch):
    carrier, _, _ = _carrier()
    parse = _contract_answering(monkeypatch, carrier)
    with pytest.raises(ConstructionPanic) as excinfo:
        parse("x", ["x"])
    _refused(excinfo, "parse_contract_expression")


def test_contract_expression_truth_carrier_is_refused_by_name(monkeypatch):
    carrier, _, _ = _carrier()
    value = SimpleNamespace(truth=lambda fragment: carrier)
    parse = _contract_answering(monkeypatch, ExitSet.completed(value))
    with pytest.raises(ConstructionPanic) as excinfo:
        parse("x", ["x"])
    _refused(excinfo, "parse_contract_expression")


# --- grouped_raise_effect ---------------------------------------------------


def test_group_leaf_subtype_carrier_is_refused_by_name():
    from sugar_lift_py_tests.effect.grouped_raise_effect import _leaf_matches

    carrier, _, _ = _carrier()
    raised = SimpleNamespace(test_python_subtype=lambda expected, site: carrier)
    leaf = SimpleNamespace(raised_value=raised)
    with pytest.raises(ConstructionPanic) as excinfo:
        _leaf_matches(leaf, None, None)
    _refused(excinfo, "GroupedRaiseEffect.partition")


# --- guarded_binding_read_sugar ---------------------------------------------


@dataclass(frozen=True)
class _ReadSite:
    filename: str = "carrier-bridge-sites.py"
    line: int = 1
    col: int = 0


def test_whole_binding_read_hands_a_carrier_on():
    from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import read_binding

    carrier, _, _ = _carrier()
    read = read_binding(
        _Answer(carrier), read_name="v", read_site=_ReadSite(), ctx=None
    )
    assert read is carrier


def test_guarded_binding_arm_carrier_is_refused_by_name():
    from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import read_binding

    carrier, _, _ = _carrier()
    state = GuardedProjection(
        BranchResultSlot("branch-result:blake3-512:carrier"),
        _Answer(carrier),
        _Answer(ExitSet.completed(TermValue(1))),
    )
    with pytest.raises(ConstructionPanic) as excinfo:
        read_binding(state, read_name="v", read_site=_ReadSite(), ctx=None)
    _refused(excinfo, "GuardedBindingReadSugar.read_binding")


# --- if_exp_sugar -----------------------------------------------------------


def test_if_exp_held_prior_carrier_is_refused_by_name():
    from sugar_lift_py_tests.sugar.if_exp_sugar import IfExpSugar

    carrier, _, _ = _carrier()
    prior = ("walrus-evaluation", "n", _Answer(carrier))
    holder = SimpleNamespace(walrus_priors=(prior,))
    with pytest.raises(ConstructionPanic) as excinfo:
        IfExpSugar._holding(holder, ExitSet.completed(TermValue(1)), None)
    _refused(excinfo, "IfExpSugar._holding")


# --- loop_recurrence_sugar --------------------------------------------------


def _next_answering(monkeypatch, answer):
    from sugar_lift_py_tests.operations import next_operation

    class _Next:
        def __init__(self, **_kwargs):
            pass

        def submit(self, iterator, ctx):
            return answer

    monkeypatch.setattr(next_operation, "NextOperation", _Next)


def test_loop_next_carrier_is_refused_by_name(monkeypatch):
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import LoopRecurrenceSugar

    carrier, _, _ = _carrier()
    _next_answering(monkeypatch, carrier)
    with pytest.raises(ConstructionPanic) as excinfo:
        LoopRecurrenceSugar._advance_iterator(
            SimpleNamespace(site=None), None, None, None, entries=(), carried=()
        )
    _refused(excinfo, "LoopRecurrenceSugar.next")


def test_loop_target_unpack_carrier_is_refused_by_name(monkeypatch):
    from sugar_lift_py_tests.operations import positional_unpack_operation
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import LoopRecurrenceSugar

    carrier, _, _ = _carrier()

    class _Unpack:
        def __init__(self, **_kwargs):
            pass

        def submit(self, current, ctx):
            return carrier

    monkeypatch.setattr(
        positional_unpack_operation, "PositionalUnpackOperation", _Unpack
    )
    pattern = SimpleNamespace(target=_expression("(a, b)"), target_coordinates=())
    with pytest.raises(ConstructionPanic) as excinfo:
        LoopRecurrenceSugar._project_iteration_target(
            SimpleNamespace(), pattern, TermValue(1), None
        )
    _refused(excinfo, "LoopRecurrenceSugar.target")


def _iterate_over(monkeypatch, body, carrier):
    """Run one item whose body reduced to ``body``; what follows is ``carrier``."""
    from sugar_lift_py_tests.floor.iterator_value import NextResult
    from sugar_lift_py_tests.sugar import function_universe_sugar
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import LoopRecurrenceSugar

    _next_answering(
        monkeypatch,
        ExitSet.completed(NextResult(value=TermValue(1), advanced=TermValue(2))),
    )
    monkeypatch.setattr(
        function_universe_sugar, "reduce_block_to_exitset", lambda sugars, ctx: body
    )
    loop = SimpleNamespace(
        site=None,
        target_cid="loop-target:" + "c" * 32,
        _project_iteration_target=lambda pattern, value, ctx: ExitSet.completed(()),
        _enter_header=lambda runtime, ctx, carried: ctx,
        _enter_target=lambda runtime, ctx, projections: (ctx, ()),
        _after_iteration_state=lambda *_args, **_kwargs: carrier,
        _after_loop_control=lambda *_args, **_kwargs: carrier,
        _after_iteration_face=lambda *_args, **_kwargs: carrier,
    )
    runtime = SimpleNamespace(target_pattern=None, body_sugars=())
    return LoopRecurrenceSugar._advance_iterator(
        loop, None, runtime, None, entries=(), carried=()
    )


def test_loop_iteration_continuation_carrier_composes_beneath_its_face(monkeypatch):
    carrier, left, right = _carrier()
    body = ExitSet(
        (
            Completed(atomic("test.first", []), TermValue(1)),
            Completed(atomic("test.second", []), TermValue(2), owed=("owed.second",)),
        )
    )
    composed = _iterate_over(monkeypatch, body, carrier)

    assert isinstance(composed, NativeOperationExitCarrierV1)
    actuals = _actuals(left, right)
    exits = composed.discharge(None, actuals)
    discharged = carrier.discharge(None, actuals)
    eager = body.sequence(lambda _state: discharged)
    assert isinstance(exits, ExitSet)
    assert exits == eager
    assert _testimony(exits) == _testimony(eager)


def test_loop_control_continuation_carrier_composes_beneath_its_halt(monkeypatch):
    carrier, left, right = _carrier()
    body = ExitSet(
        (
            Halted(
                atomic("test.first", []),
                _raise_effect("loop-control"),
                None,
                owed=("owed.halt",),
            ),
            Completed(atomic("test.second", []), TermValue(2)),
        )
    )
    composed = _iterate_over(monkeypatch, body, carrier)

    assert isinstance(composed, NativeOperationExitCarrierV1)
    actuals = _actuals(left, right)
    exits = composed.discharge(None, actuals)
    discharged = carrier.discharge(None, actuals)
    eager = body.sequence(lambda _state: discharged, consume=lambda _halt: discharged)
    assert isinstance(exits, ExitSet)
    assert exits == eager
    assert _testimony(exits) == _testimony(eager)
    assert any("owed.halt" in exit_.owed for exit_ in exits.exits)


def test_loop_single_face_continuation_carrier_keeps_its_face(monkeypatch):
    carrier, left, right = _carrier()
    body = ExitSet(
        (Completed(atomic("test.only", []), TermValue(1), owed=("owed.only",)),)
    )
    composed = _iterate_over(monkeypatch, body, carrier)

    assert isinstance(composed, NativeOperationExitCarrierV1)
    actuals = _actuals(left, right)
    exits = composed.discharge(None, actuals)
    discharged = carrier.discharge(None, actuals)
    eager = body.sequence(lambda _state: discharged)
    assert isinstance(exits, ExitSet)
    assert exits == eager
    # The face's debt rides onto what follows it; it is never dropped.
    assert exits.exits
    assert all("owed.only" in exit_.owed for exit_ in exits.exits)


def test_loop_body_carrier_continues_the_loop_once_it_discharges(monkeypatch):
    # The item's body itself waits on its caller's actuals. Once it
    # discharges, the loop continues from this item (``following`` runs
    # beneath the body's face), and the face's debt rides onto it.
    carrier, left, right = _carrier()
    body_guard = atomic("test.body", [])
    body = carrier.and_then(
        lambda value: ExitSet((Completed(body_guard, value, owed=("owed.body",)),))
    )
    following = ExitSet.completed(TermValue(99))

    composed = _iterate_over(monkeypatch, body, following)

    assert isinstance(composed, NativeOperationExitCarrierV1)
    actuals = _actuals(left, right)
    exits = composed.discharge(None, actuals)
    discharged = body.discharge(None, actuals)
    eager = discharged.sequence(lambda _state: following)
    assert isinstance(exits, ExitSet)
    assert exits == eager
    assert _testimony(exits) == _testimony(eager)
    # The loop did not stop at the body: what follows the item is the answer.
    assert [exit_.value for exit_ in exits.exits] == [TermValue(99)]
    assert all("owed.body" in exit_.owed for exit_ in exits.exits)


def test_loop_body_carrier_with_several_faces_continues_each(monkeypatch):
    carrier, left, right = _carrier()
    first_guard = atomic("test.first", [])
    second_guard = atomic("test.second", [])
    body = carrier.and_then(
        lambda value: ExitSet(
            (
                Completed(first_guard, value, owed=("owed.first",)),
                Completed(second_guard, TermValue(5), owed=("owed.second",)),
            )
        )
    )
    following = ExitSet.completed(TermValue(99))

    composed = _iterate_over(monkeypatch, body, following)

    assert isinstance(composed, NativeOperationExitCarrierV1)
    actuals = _actuals(left, right)
    exits = composed.discharge(None, actuals)
    eager = body.discharge(None, actuals).sequence(lambda _state: following)
    assert isinstance(exits, ExitSet)
    assert exits == eager
    assert _testimony(exits) == _testimony(eager)
    owed = [debt for exit_ in exits.exits for debt in exit_.owed]
    assert "owed.first" in owed
    assert "owed.second" in owed


def _stop_iteration_halt(owed):
    from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

    stop_identity, _ = _builtin_exception_identity("StopIteration")
    effect = RaiseEffect(
        exception_name="StopIteration",
        occurrence=AuthenticatedRaiseLocus.of("loop-exhaustion"),
        exception_type_coordinate=stop_identity,
        exception_type_mro=(stop_identity,),
    )
    return Halted(atomic("test.exhausted", []), effect, None, owed=owed)


def test_loop_exhaustion_carrier_composes_beneath_the_stop_iteration(monkeypatch):
    # The loop's finish (its ``else`` suite) waits on its caller's actuals.
    # It is composed beneath the StopIteration arm the loop consumes: the
    # arm's guard and debt survive into what the loop leaves with.
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import LoopRecurrenceSugar

    carrier, left, right = _carrier()
    stop = _stop_iteration_halt(("owed.next",))
    _next_answering(monkeypatch, ExitSet((stop,)))
    loop = SimpleNamespace(
        site=None,
        _finish_iterator=lambda *_args, **_kwargs: carrier,
    )

    composed = LoopRecurrenceSugar._advance_iterator(
        loop, None, SimpleNamespace(), None, entries=(), carried=()
    )

    assert isinstance(composed, NativeOperationExitCarrierV1)
    actuals = _actuals(left, right)
    exits = composed.discharge(None, actuals)
    discharged = carrier.discharge(None, actuals)
    eager = ExitSet((stop,)).sequence(
        ExitSet.completed, consume=lambda _halt: discharged
    )
    assert isinstance(exits, ExitSet)
    assert exits == eager
    assert _testimony(exits) == _testimony(eager)
    (arm,) = exits.exits
    assert isinstance(arm, Completed)
    assert arm.value == TermValue(3)
    assert "owed.next" in arm.owed
    assert "test.exhausted" in str(arm.guard)


def _finish_with_else(monkeypatch, otherwise):
    """Finish a loop whose ``else`` suite reduced to ``otherwise``; each
    publication answers ``("published", entries)``."""
    from sugar_lift_py_tests.sugar import function_universe_sugar
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import LoopRecurrenceSugar

    monkeypatch.setattr(
        function_universe_sugar,
        "reduce_block_to_exitset",
        lambda sugars, ctx: otherwise,
    )

    def publish(
        runtime, ctx, *, entries, carried, fall_through=(), can_fall_through=True
    ):
        return ExitSet.completed(("published", entries))

    loop = SimpleNamespace(
        _enter_header=lambda runtime, ctx, carried: ctx,
        _leave_target=lambda runtime, ctx, items: ctx,
        _after_else=lambda runtime, ctx: (),
        _publish_runtime_bindings=publish,
    )
    return LoopRecurrenceSugar._finish_iterator(
        loop,
        SimpleNamespace(else_sugars=("else",)),
        None,
        entries=("before",),
        carried=(),
    )


def test_loop_else_with_several_faces_publishes_beneath_each(monkeypatch):
    # Every completed face of the ``else`` suite leaves the loop with its
    # bindings published beneath it, under its guard and faces, owing what it
    # owes; a halt of the suite leaves as it is.
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    face, _ = partition("carrier-bridge-sites.else")
    first = Completed(
        atomic("test.else.first", []),
        _ReducedBlock(("first",), True, ()),
        frozenset({face}),
        ("owed.first",),
    )
    second = Completed(
        atomic("test.else.second", []),
        _ReducedBlock(("second",), True, ()),
        owed=("owed.second",),
    )
    raised = Halted(atomic("test.else.raised", []), _raise_effect("else-raise"))

    finished = _finish_with_else(monkeypatch, ExitSet((first, second, raised)))

    assert isinstance(finished, ExitSet)
    arms = {
        exit_.value: exit_ for exit_ in finished.exits if isinstance(exit_, Completed)
    }
    assert set(arms) == {
        ("published", ("before", "first")),
        ("published", ("before", "second")),
    }
    published_first = arms[("published", ("before", "first"))]
    published_second = arms[("published", ("before", "second"))]
    assert "test.else.first" in str(published_first.guard)
    assert face in published_first.faces
    assert "owed.first" in published_first.owed
    assert "test.else.second" in str(published_second.guard)
    assert "owed.second" in published_second.owed
    assert raised in finished.exits


def test_loop_else_carrier_publishes_once_it_discharges(monkeypatch):
    # The ``else`` suite waits on its caller's actuals. Once it discharges,
    # the loop publishes its bindings beneath the suite's face exactly as it
    # does beneath a suite reduced here: the face's guard and debt survive.
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    carrier, left, right = _carrier()
    else_guard = atomic("test.else", [])
    otherwise = carrier.and_then(
        lambda value: ExitSet(
            (
                Completed(
                    else_guard,
                    _ReducedBlock((value,), True, ()),
                    owed=("owed.else",),
                ),
            )
        )
    )

    finished = _finish_with_else(monkeypatch, otherwise)

    assert isinstance(finished, NativeOperationExitCarrierV1)
    actuals = _actuals(left, right)
    exits = finished.discharge(None, actuals)
    eager = _finish_with_else(monkeypatch, otherwise.discharge(None, actuals))
    assert isinstance(exits, ExitSet)
    assert exits == eager
    assert _testimony(exits) == _testimony(eager)
    (arm,) = exits.exits
    assert isinstance(arm, Completed)
    # The loop did not stop at the else: its publication is the answer.
    assert arm.value == ("published", ("before", TermValue(3)))
    assert "test.else" in str(arm.guard)
    assert "owed.else" in arm.owed


def test_loop_outward_face_carrier_is_refused_by_name():
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
        _outward_face_partition,
    )

    carrier, _, _ = _carrier()
    face = SimpleNamespace(guard=atomic("test.face", []), state=None)
    with pytest.raises(ConstructionPanic) as excinfo:
        _outward_face_partition(carrier, face, guarded=True)
    _refused(excinfo, "LoopRecurrenceSugar.outward_face")


# --- spread_sugar -----------------------------------------------------------


def test_spread_finish_carrier_composes_through_after_discharge():
    from sugar_lift_py_tests.sugar.spread_sugar import _collect

    carrier, left, right = _carrier()
    deferred = _collect((), None, (), lambda _values: carrier)
    assert isinstance(deferred, NativeOperationExitCarrierV1)
    exits = deferred.discharge(
        None, {left.coordinate_cid: TermValue(1), right.coordinate_cid: TermValue(2)}
    )
    assert isinstance(exits, ExitSet)
    assert [exit_.value for exit_ in exits.exits] == [TermValue(3)]


# --- try_sugar / try_star_sugar ---------------------------------------------


def test_try_handler_matcher_carrier_is_refused_by_name():
    from sugar_lift_py_tests.sugar.try_sugar import _effect_match_verdict

    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _effect_match_verdict(_raise_effect("try-matcher"), _Answer(carrier))
    _refused(excinfo, "TrySugar.handler-matcher")


def test_try_star_handler_matcher_carrier_is_refused_by_name():
    from sugar_lift_py_tests.sugar.try_star_sugar import _matcher_value

    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _matcher_value(_Answer(carrier), None)
    _refused(excinfo, "TryStarSugar.handler-matcher")


def test_try_star_statement_carrier_composes_beneath_its_prefix(monkeypatch):
    from sugar_lift_py_tests.sugar import function_universe_sugar
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
    from sugar_lift_py_tests.sugar.try_star_sugar import _reduce_block_from_state

    carrier, left, right = _carrier()

    def reduce(sugars, ctx):
        (statement,) = sugars
        if statement == "deferred":
            return carrier.and_then(
                lambda value: ExitSet.completed(_ReducedBlock((value,), True, ()))
            )
        return ExitSet.completed(_ReducedBlock((statement,), True, ()))

    monkeypatch.setattr(function_universe_sugar, "reduce_block_to_exitset", reduce)
    prefix = _ReducedBlock(("before",), True, ())

    deferred = _reduce_block_from_state(("deferred", "after"), prefix, None)

    assert isinstance(deferred, NativeOperationExitCarrierV1)
    exits = deferred.discharge(None, _actuals(left, right))
    assert isinstance(exits, ExitSet)
    (arm,) = exits.exits
    assert isinstance(arm, Completed)
    # The prefix before the deferred statement, then what it and the later
    # statement reduced to, in order.
    assert arm.value.entries == ("before", TermValue(3), "after")


def test_try_star_handler_carrier_is_refused_by_name():
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from test_try_compositions_carry_owed_7825 import _Fixed, _one_leaf_try_star

    carrier, _, _ = _carrier()
    sugar, _leaf = _one_leaf_try_star(
        "handler_carrier", lambda _leaf: (_Fixed(lambda _c: carrier),)
    )
    with pytest.raises(ConstructionPanic) as excinfo:
        sugar.desugar(ReduceContext.root(owner="handler_carrier"))
    _refused(excinfo, "TryStarSugar.handler")


def test_try_star_body_carrier_routes_its_halt_once_it_discharges(monkeypatch):
    # The try* body itself waits on its caller's actuals. Once it discharges,
    # its group halt reaches the handler exactly as a body reduced here does:
    # the try* completes under the body halt's guard and owes what the body
    # halt owed and what the handler owed.
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.sugar import function_universe_sugar
    from test_try_compositions_carry_owed_7825 import (
        _Fixed,
        _one_leaf_try_star,
        _owing_completion,
    )

    carrier, left, right = _carrier()
    sugar, _leaf = _one_leaf_try_star(
        "body_carrier",
        lambda _leaf: (_Fixed(lambda c: _owing_completion(c, "debt:handler")),),
    )
    (halt,) = sugar.body[0].desugar(None).exits
    owing = ExitSet((Halted(halt.guard, halt.effect, halt.state, owed=("debt:body",)),))
    deferred = carrier.and_then(lambda _value: owing)

    real = function_universe_sugar.reduce_block_to_exitset

    def reduce(sugars, ctx):
        return deferred if sugars is sugar.body else real(sugars, ctx)

    monkeypatch.setattr(function_universe_sugar, "reduce_block_to_exitset", reduce)

    composed = sugar.desugar(ReduceContext.root(owner="body_carrier"))

    assert isinstance(composed, NativeOperationExitCarrierV1)
    exits = composed.discharge(None, _actuals(left, right))
    assert isinstance(exits, ExitSet)
    assert [type(arm) for arm in exits.exits] == [Completed], exits.exits
    (completed,) = exits.exits
    assert "body.guard" in str(completed.guard), completed.guard
    assert completed.owed == ("debt:body", "debt:handler")


def test_try_star_body_carrier_completion_runs_the_else(monkeypatch):
    # A body that completes once it discharges runs the ``else`` suite beneath
    # its arm, which owes what the body owed.
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.sugar import function_universe_sugar
    from sugar_lift_py_tests.sugar.try_star_sugar import TryStarSugar

    carrier, left, right = _carrier()
    sugar = TryStarSugar(body=("deferred-body",), handlers=(), orelse=("else",))
    body_guard = atomic("test.body", [])
    deferred = carrier.and_then(
        lambda value: ExitSet((Completed(body_guard, value, owed=("owed.body",)),))
    )

    real = function_universe_sugar.reduce_block_to_exitset

    def reduce(sugars, ctx):
        if sugars is sugar.body:
            return deferred
        if sugars is sugar.orelse:
            return ExitSet.completed(TermValue(42))
        return real(sugars, ctx)

    monkeypatch.setattr(function_universe_sugar, "reduce_block_to_exitset", reduce)

    composed = sugar.desugar(ReduceContext.root(owner="body_carrier_else"))

    assert isinstance(composed, NativeOperationExitCarrierV1)
    exits = composed.discharge(None, _actuals(left, right))
    assert isinstance(exits, ExitSet)
    (arm,) = exits.exits
    assert isinstance(arm, Completed)
    # The try* continued past the body into its ``else``.
    assert arm.value == TermValue(42)
    assert "test.body" in str(arm.guard)
    assert "owed.body" in arm.owed


# --- function_universe_sugar ------------------------------------------------


def test_prior_returns_join_a_composed_carrier_once_it_discharges():
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _beside_prior_returns,
    )

    carrier, left, right = _carrier()
    returned = Completed(atomic("test.returned", []), TermValue(9))

    composed = _beside_prior_returns(carrier, (returned,))

    assert isinstance(composed, NativeOperationExitCarrierV1)
    exits = composed.discharge(None, _actuals(left, right))
    assert isinstance(exits, ExitSet)
    eager = _beside_prior_returns(
        carrier.discharge(None, _actuals(left, right)), (returned,)
    )
    assert exits == eager
    values = [exit_.value for exit_ in exits.exits]
    assert TermValue(3) in values
    assert TermValue(9) in values


# --- with_source_resource_sugar / with_formal_manager_sugar -----------------


class _Receiver:
    """A manager value whose receiver projection answers ``answer`` (itself
    when None)."""

    def __init__(self, answer=None):
        self.answer = answer

    def project_operation_receiver_outcome(self, ctx, *, owner):
        return ExitSet.completed(self) if self.answer is None else self.answer

    def to_term(self, *, owner):
        return str_const("carrier-bridge-sites.manager")


def _protocol(*, enter=None, exit_=None, concrete_exit=None):
    entered = ExitSet.completed(SimpleNamespace(enter_value=TermValue(1)))
    enter_answer = entered if enter is None else enter
    protocol = SimpleNamespace(
        enter_resource_outcome_for=lambda manager, ctx: enter_answer,
        exit_outcome_for=lambda entered, ctx: exit_,
    )
    if concrete_exit is not None:
        protocol.exit_outcome_for_body = lambda entered, body_face, ctx: concrete_exit
    return protocol


def _source_resource(protocol):
    return SimpleNamespace(
        manager=_Answer(ExitSet.completed(_Receiver())),
        manager_slot_id="carrier-bridge-sites.manager-slot",
        enter_slot_id=None,
        exit_face_id="carrier-bridge-sites.exit-face",
        body=(),
        protocol=protocol,
        site=None,
    )


@pytest.fixture
def _empty_body(monkeypatch):
    from sugar_lift_py_tests.sugar import function_universe_sugar

    monkeypatch.setattr(
        function_universe_sugar,
        "reduce_block_to_exitset",
        lambda sugars, ctx: ExitSet.completed(TermValue(0)),
    )


def test_source_resource_manager_carrier_is_refused_by_name():
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        _route_manager_faces,
    )

    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _route_manager_faces(SimpleNamespace(manager=_Answer(carrier)), None)
    _refused(excinfo, "WithSourceResourceSugar.manager")


def test_source_resource_receiver_projection_carrier_is_refused_by_name():
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        _project_manager_receiver,
    )

    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _project_manager_receiver(_Receiver(carrier), None)
    _refused(excinfo, "WithSourceResourceSugar.manager")


def test_source_resource_enter_carrier_is_refused_by_name():
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        _route_manager_faces,
    )

    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _route_manager_faces(_source_resource(_protocol(enter=carrier)), None)
    _refused(excinfo, "WithSourceResourceSugar.enter")


def test_source_resource_abstract_exit_carrier_is_refused_by_name(_empty_body):
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        _route_manager_faces,
    )

    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _route_manager_faces(_source_resource(_protocol(exit_=carrier)), None)
    _refused(excinfo, "WithSourceResourceSugar.exit")


def test_source_resource_concrete_exit_carrier_is_refused_by_name(_empty_body):
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        _route_manager_faces,
    )

    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _route_manager_faces(_source_resource(_protocol(concrete_exit=carrier)), None)
    _refused(excinfo, "WithSourceResourceSugar.exit")


def _formal_manager(manager, protocol):
    from sugar_lift_py_tests.sugar.with_formal_manager_sugar import (
        WithFormalManagerSugar,
    )

    return _bare(
        WithFormalManagerSugar,
        manager=manager,
        protocol=protocol,
        summary=None,
        body=(),
        manager_slot_id="carrier-bridge-sites.manager-slot",
        enter_slot_id=None,
        exit_face_id="carrier-bridge-sites.exit-face",
        site=None,
    )


def test_formal_manager_manager_carrier_is_refused_by_name():
    carrier, _, _ = _carrier()
    sugar = _formal_manager(_Answer(carrier), _protocol())
    with pytest.raises(ConstructionPanic) as excinfo:
        sugar.desugar(None)
    _refused(excinfo, "WithFormalManagerSugar.manager")


def test_formal_manager_enter_carrier_is_refused_by_name():
    carrier, _, _ = _carrier()
    sugar = _formal_manager(
        _Answer(ExitSet.completed(_Receiver())), _protocol(enter=carrier)
    )
    with pytest.raises(ConstructionPanic) as excinfo:
        sugar.desugar(None)
    _refused(excinfo, "WithFormalManagerSugar.enter")


def test_formal_manager_construct_carrier_is_refused_by_name():
    carrier, _, _ = _carrier()
    protocol = _protocol()
    protocol.construct_manager = lambda value, ctx: carrier
    sugar = _formal_manager(_Answer(ExitSet.completed(_Receiver())), protocol)
    with pytest.raises(ConstructionPanic) as excinfo:
        sugar.desugar(None)
    _refused(excinfo, "WithFormalManagerSugar.construct")


def test_formal_manager_exit_carrier_is_refused_by_name(_empty_body):
    carrier, _, _ = _carrier()
    sugar = _formal_manager(
        _Answer(ExitSet.completed(_Receiver())), _protocol(exit_=carrier)
    )
    with pytest.raises(ConstructionPanic) as excinfo:
        sugar.desugar(None)
    _refused(excinfo, "WithFormalManagerSugar.exit")


@pytest.fixture
def _carrier_body(monkeypatch):
    """A ``with`` body that reduces to a deferred carrier."""
    from sugar_lift_py_tests.sugar import function_universe_sugar

    carrier, _, _ = _carrier()
    monkeypatch.setattr(
        function_universe_sugar,
        "reduce_block_to_exitset",
        lambda sugars, ctx: carrier,
    )


def test_source_resource_body_carrier_is_refused_by_name(_carrier_body):
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        _route_manager_faces,
    )

    with pytest.raises(ConstructionPanic) as excinfo:
        _route_manager_faces(_source_resource(_protocol()), None)
    _refused(excinfo, "WithSourceResourceSugar.body")


def test_formal_manager_body_carrier_is_refused_by_name(_carrier_body):
    sugar = _formal_manager(_Answer(ExitSet.completed(_Receiver())), _protocol())
    with pytest.raises(ConstructionPanic) as excinfo:
        sugar.desugar(None)
    _refused(excinfo, "WithFormalManagerSugar.body")


# --- the other with sugars (former ``sugar_outcome_to_exitset`` sites) ------


def _with_resource(**fields):
    from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar

    base = dict(
        manager=_Answer(ExitSet.completed(TermValue(5))),
        manager_slot_id="carrier-bridge-sites.manager-slot",
        enter=_Answer(ExitSet.completed(TermValue(6))),
        exit=_Answer(ExitSet.completed(TermValue(7))),
        exit_face_id="carrier-bridge-sites.exit-face",
        body=(),
        disposition=None,
        enter_slot_id=None,
        site=None,
    )
    base.update(fields)
    return _bare(WithResourceSugar, **base)


def test_with_resource_manager_carrier_is_refused_by_name():
    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _with_resource(manager=_Answer(carrier)).desugar(None)
    _refused(excinfo, "WithResourceSugar.manager")


def test_with_resource_enter_carrier_is_refused_by_name():
    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _with_resource(enter=_Answer(carrier)).desugar(None)
    _refused(excinfo, "WithResourceSugar.enter")


def test_with_resource_exit_carrier_is_refused_by_name(_empty_body):
    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _with_resource(exit=_Answer(carrier)).desugar(None)
    _refused(excinfo, "WithResourceSugar.exit")


def test_with_resource_body_carrier_is_refused_by_name(_carrier_body):
    with pytest.raises(ConstructionPanic) as excinfo:
        _with_resource().desugar(None)
    _refused(excinfo, "WithResourceSugar.body")


def test_with_opaque_cited_manager_carrier_is_refused_by_name():
    from sugar_lift_py_tests.sugar.with_opaque_cited_manager_sugar import (
        WithOpaqueCitedManagerSugar,
    )

    carrier, _, _ = _carrier()
    sugar = _bare(
        WithOpaqueCitedManagerSugar,
        manager=_Answer(carrier),
        body=(),
        contract_ref=None,
        enter_slot_id=None,
        site=None,
    )
    with pytest.raises(ConstructionPanic) as excinfo:
        sugar.desugar(None)
    _refused(excinfo, "WithOpaqueCitedManagerSugar.manager")


def test_with_effect_boundary_manager_carrier_is_refused_by_name(monkeypatch):
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )

    carrier, _, _ = _carrier()
    monkeypatch.setattr(WithEffectBoundarySugar, "_semantics_faces", lambda self: ())
    sugar = _bare(
        WithEffectBoundarySugar,
        manager=_Answer(carrier),
        body=(),
        semantics=None,
        contract_ref=None,
        context_manager_edge=None,
        site=None,
    )
    with pytest.raises(ConstructionPanic) as excinfo:
        sugar.desugar(None)
    _refused(excinfo, "WithEffectBoundarySugar.manager")


def test_generator_with_manager_carrier_is_refused_by_name():
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    carrier, _, _ = _carrier()
    sugar = _bare(
        GeneratorWithSugar,
        manager=_Answer(carrier),
        body=(),
        enter_slot_id=None,
        site=None,
    )
    with pytest.raises(ConstructionPanic) as excinfo:
        sugar.desugar(None)
    _refused(excinfo, "GeneratorWithSugar.manager")


def test_generator_object_with_manager_carrier_is_refused_by_name(monkeypatch):
    from sugar_lift_py_tests import generator_object_with_refusal
    from sugar_lift_py_tests.sugar.generator_with_sugar import (
        GeneratorObjectWithSugar,
    )

    carrier, _, _ = _carrier()
    monkeypatch.setattr(
        generator_object_with_refusal,
        "observed_generator_object_with_refusal",
        lambda kind: None,
    )
    sugar = _bare(
        GeneratorObjectWithSugar,
        manager=_Answer(carrier),
        site=None,
        object_kind="generator",
    )
    with pytest.raises(ConstructionPanic) as excinfo:
        sugar.desugar(None)
    _refused(excinfo, "GeneratorObjectWithSugar.manager")


def test_non_manager_object_with_manager_carrier_is_refused_by_name(monkeypatch):
    from sugar_lift_py_tests import manager_protocol_absence_refusal
    from sugar_lift_py_tests.sugar.generator_with_sugar import (
        NonManagerObjectWithSugar,
    )

    carrier, _, _ = _carrier()
    monkeypatch.setattr(
        manager_protocol_absence_refusal,
        "observed_non_manager_with_refusal",
        lambda type_name, *, has_enter, has_exit: None,
    )
    sugar = _bare(
        NonManagerObjectWithSugar,
        manager=_Answer(carrier),
        site=None,
        type_name="C",
        has_enter=False,
        has_exit=False,
    )
    with pytest.raises(ConstructionPanic) as excinfo:
        sugar.desugar(None)
    _refused(excinfo, "NonManagerObjectWithSugar.manager")


# --- manager_protocol_construction -----------------------------------------


def test_receiver_state_after_enter_carrier_is_refused_by_name():
    from sugar_lift_python_source.manager_protocol_construction import (
        _receiver_state_after_enter,
    )

    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _receiver_state_after_enter(None, carrier, blame="carrier-bridge-sites")
    _refused(excinfo, "ConstructedManagerProtocolV1.receiver_state_after_enter")


def test_resource_enter_transitions_carrier_is_refused_by_name():
    from sugar_lift_python_source.manager_protocol_construction import (
        _resource_enter_transitions,
    )

    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _resource_enter_transitions(None, carrier, blame="carrier-bridge-sites")
    _refused(excinfo, "ConstructedManagerProtocolV1.resource_enter_transitions")


def test_generator_enter_yield_carrier_is_refused_by_name():
    from sugar_lift_python_source.manager_protocol_construction import (
        _floor_enter_value,
    )

    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _floor_enter_value(_Answer(carrier))
    _refused(excinfo, "GeneratorBackedManagerProtocolV1.enter_resource_outcome")


def _partitioned_protocol(monkeypatch, answer_for):
    """A protocol over a receiver partition whose ``name`` call answers
    ``answer_for(name)``."""
    from sugar_lift_python_source import manager_protocol_construction as mpc

    monkeypatch.setattr(
        mpc,
        "_completed_receiver_exits",
        lambda receiver_state: ExitSet.completed(TermValue(0)),
    )
    monkeypatch.setattr(
        mpc,
        "_call_protocol_method",
        lambda receiver, name, arguments, exit_face_id, ctx: answer_for(name),
    )
    return _bare(
        mpc.ConstructedManagerProtocolV1,
        receiver_state="partitioned-receiver",
        exit_face_id="carrier-bridge-sites.exit-face",
    )


def test_partitioned_enter_outcome_carrier_is_refused_by_name(monkeypatch):
    carrier, _, _ = _carrier()
    protocol = _partitioned_protocol(monkeypatch, lambda name: carrier)
    with pytest.raises(ConstructionPanic) as excinfo:
        protocol.enter_outcome()
    _refused(excinfo, "ConstructedManagerProtocolV1.enter_outcome")


def test_partitioned_exit_outcome_carrier_is_refused_by_name(monkeypatch):
    carrier, _, _ = _carrier()

    def answer_for(name):
        if name == "__exit__":
            return carrier
        return ExitSet.completed(TermValue(1))

    protocol = _partitioned_protocol(monkeypatch, answer_for)
    with pytest.raises(ConstructionPanic) as excinfo:
        protocol.exit_outcome()
    _refused(excinfo, "ConstructedManagerProtocolV1.exit_outcome")


# --- manager_summary_derivation ---------------------------------------------


def test_signature_default_carrier_is_refused_by_name():
    from sugar_lift_python_source.manager_summary_derivation import (
        _signature_for_behavior,
    )

    carrier, _, _ = _carrier()
    behavior = SimpleNamespace(
        source_call_frame=SimpleNamespace(
            parameters=("p",),
            parameter_kinds=("positional_or_keyword",),
            default_sugars=(_Answer(carrier),),
        )
    )
    with pytest.raises(ConstructionPanic) as excinfo:
        _signature_for_behavior(behavior, None)
    _refused(excinfo, "ManagerSummary.signature-default")


def test_constructor_application_from_spread_carrier_is_refused_by_name():
    from sugar_lift_python_source.manager_summary_derivation import (
        _constructor_application_from_spread,
    )

    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _constructor_application_from_spread(_Answer(carrier), None)
    _refused(excinfo, "_read_same_module_class_head.collect_application")


def test_receiver_from_constructor_outcome_carrier_is_refused_by_name():
    from sugar_lift_python_source.manager_summary_derivation import (
        _receiver_from_constructor_outcome,
    )

    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _receiver_from_constructor_outcome(carrier)
    _refused(excinfo, "_receiver_from_constructor_outcome")


def test_retained_constructor_completion_carrier_is_refused_by_name():
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_python_source.manager_summary_derivation import (
        _receiver_from_constructor_outcome,
    )

    carrier, _, _ = _carrier()

    class _RetainingCall(CallSiteValue):
        """A call whose retained completion is still a deferred carrier."""

        __eq__ = object.__eq__
        __hash__ = object.__hash__

        def retained_source_completion_outcome(self):
            return carrier

    call = object.__new__(_RetainingCall)
    with pytest.raises(ConstructionPanic) as excinfo:
        _receiver_from_constructor_outcome(ExitSet.completed(call))
    _refused(excinfo, "_receiver_from_constructor_outcome")


def test_same_module_class_head_carrier_is_refused_by_name():
    from sugar_lift_python_source.manager_summary_derivation import (
        _read_same_module_class_head,
    )

    carrier, _, _ = _carrier()
    class_def = SimpleNamespace(name="C", sugar=lambda: _Answer(carrier))
    with pytest.raises(ConstructionPanic) as excinfo:
        _read_same_module_class_head(
            None,
            None,
            None,
            "carrier-bridge-sites.exit-face",
            class_def,
            reduce_ctx=None,
        )
    _refused(excinfo, "_read_same_module_class_head")


def test_module_returned_by_call_carrier_is_refused_by_name():
    from sugar_lift_python_source.manager_summary_derivation import (
        _module_returned_by_call,
    )

    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic) as excinfo:
        _module_returned_by_call(SimpleNamespace(sugar=lambda: _Answer(carrier)))
    _refused(excinfo, "_module_returned_by_call")


# --- sugar_source_tree.nodes ------------------------------------------------


def test_assign_constructed_floor_value_carrier_is_refused_by_name():
    from sugar_source_tree.nodes import Assign

    carrier, _, _ = _carrier()
    value = SimpleNamespace(sugar=lambda: _Answer(carrier), fragment=None)
    with pytest.raises(ConstructionPanic) as excinfo:
        Assign._constructed_floor_value(value)
    _refused(excinfo, "Assign._constructed_floor_value")
