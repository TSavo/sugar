"""#7825 / #7757: manager arm lists that were assembled by hand now compose.

Every rewritten site in ``sugar_lift_python_source`` composes a step with
what follows through ``ExitSet.sequence`` (``consume=`` for a halt the
composition owns), joins sibling sets through ``ExitSet.union``, or builds one
fresh arm with ``ExitSet.completed``. Four of the hand assemblies dropped what
an arm carried (its guard, its partition testimony or what it owed); each has
a test here that it now survives.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import (
    ObjectField,
    ObjectValue,
    ReceiverStatePartitionValue,
    TermValue,
)
from sugar_lift_py_tests.ir import and_, atomic
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    complement_guard,
    partition,
)

from frame_fresh import FRAME_FRESH


def _raise(name: str) -> RaiseEffect:
    return RaiseEffect.for_builtin("ValueError", occurrence=f"test:{name}:7825")


@dataclass(frozen=True)
class _Method:
    name: str


def test_a_floored_receiver_face_keeps_its_faces_and_owed() -> None:
    # The rebuild ``type(face)(face.guard, floored)`` stated the guard alone:
    # the face's partition testimony and its debts were dropped. The floored
    # receiver holds exactly the fields it stored: none is invented (#8104).
    from sugar_lift_py_tests.floor.class_value import ClassValue
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_python_source.manager_construction import (
        _floor_tuple_construct_fields,
    )

    side, _other = partition(("test:floor-tuple-face", 7825))
    guard = atomic("test:floor-tuple:7825", [])
    expected = ClassValue("Expected", (), None)
    # ``expected if isinstance(...) else () if ... is None else (expected,)``:
    # the stored wrap floors to its singleton arm for one class actual.
    wrap = GuardedValue(
        atomic("test:is-tuple:7825", []),
        expected,
        GuardedValue(
            atomic("test:is-none:7825", []),
            TupleValue(()),
            TupleValue((expected,)),
        ),
    )
    receiver = ObjectValue(
        "Manager",
        (ObjectField("expected", wrap),),
        methods=(_Method("check"),),
        allocation=FRAME_FRESH,
    )
    halt = Halted(complement_guard(guard), _raise("floor-halt"))
    state = ReceiverStatePartitionValue(
        ExitSet(
            (
                Completed(guard, receiver, frozenset({side}), ("debt:face",)),
                halt,
            )
        )
    )

    floored = _floor_tuple_construct_fields(state, (expected,))

    assert isinstance(floored, ReceiverStatePartitionValue)
    arm, stood = floored.exits.exits
    assert isinstance(arm, Completed)
    assert arm.value is not receiver
    assert arm.value.fields == (ObjectField("expected", TupleValue((expected,))),)
    assert arm.value.methods == receiver.methods
    assert arm.guard == guard
    assert arm.faces == frozenset({side})
    assert arm.owed == ("debt:face",)
    # A constructor halt stands as it was.
    assert stood == halt


def test_a_nested_receiver_leaf_keeps_its_whole_path() -> None:
    # A nested leaf was rebuilt under the enclosing face's guard alone: the
    # leaf's own guard, both faces' testimony and the leaf's debts dropped.
    from sugar_lift_python_source.manager_protocol_construction import (
        _completed_receiver_exits,
    )

    outer_side, _outer_other = partition(("test:outer-receiver", 7825))
    inner_side, _inner_other = partition(("test:inner-receiver", 7825))
    outer = atomic("test:outer:7825", [])
    inner = atomic("test:inner:7825", [])
    leaf = ObjectValue("Manager", (), allocation=FRAME_FRESH)
    nested = ReceiverStatePartitionValue(
        ExitSet(
            (
                Completed(inner, leaf, frozenset({inner_side}), ("debt:inner",)),
                Halted(complement_guard(inner), _raise("inner-halt")),
            )
        )
    )
    state = ReceiverStatePartitionValue(
        ExitSet(
            (
                Completed(outer, nested, frozenset({outer_side}), ("debt:outer",)),
                Halted(complement_guard(outer), _raise("outer-halt")),
            )
        )
    )

    (arm,) = _completed_receiver_exits(state).exits

    assert isinstance(arm, Completed)
    assert arm.value is leaf
    assert arm.guard == and_([outer, inner])
    assert arm.faces == frozenset({outer_side, inner_side})
    assert arm.owed == ("debt:outer", "debt:inner")


def test_a_factored_boundary_face_keeps_its_partition_testimony(
    monkeypatch,
) -> None:
    # Each boundary face was rebuilt from guard and ``owed`` alone: the
    # receiver face's partition testimony was dropped.
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        NoMessagePatternV1,
        OptionalFormalArgumentProjectionV1,
    )
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_python_source import manager_summary_derivation as msd

    none_side, pattern_side = partition(("test:match-face", 7825))
    guard = atomic("test:match-none:7825", [])
    no_pattern = ObjectValue(
        "Manager", (ObjectField("match", NoneValue()),), allocation=FRAME_FRESH
    )
    pattern = ObjectValue(
        "Manager", (ObjectField("match", TermValue(1)),), allocation=FRAME_FRESH
    )
    behavior = SimpleNamespace(
        receiver_state=ReceiverStatePartitionValue(
            ExitSet(
                (
                    Completed(
                        guard, no_pattern, frozenset({none_side}), ("debt:none",)
                    ),
                    Completed(
                        complement_guard(guard),
                        pattern,
                        frozenset({pattern_side}),
                        ("debt:pattern",),
                    ),
                )
            )
        )
    )

    def semantics(message_pattern_operand):
        return EffectBoundarySemanticsV1(
            mode="test-mode",
            effect_kind="test-effect",
            expected_type_operand="test-expected",
            message_pattern_operand=message_pattern_operand,
            binding="test-binding",
        )

    none_boundary = semantics(NoMessagePatternV1())
    pattern_boundary = semantics(OptionalFormalArgumentProjectionV1(1))
    monkeypatch.setattr(
        msd,
        "_derive_boundary_for_receiver",
        lambda protocol, behavior, receiver: (
            none_boundary if receiver is no_pattern else pattern_boundary
        ),
    )
    monkeypatch.setattr(
        msd, "_signature_for_behavior", lambda behavior, semantics: "signature"
    )
    protocol = SimpleNamespace(
        receiver_state=None,
        protocol_construction_cid="test-protocol",
        enter_frame_cid="test-enter",
        exit_frame_cid="test-exit",
    )

    summary = msd._derive_factored_effect_boundary(protocol, behavior)

    assert isinstance(summary, msd.FactoredEffectBoundarySummaryV1)
    none_arm, pattern_arm = summary.boundary_faces.exits
    assert none_arm.value is none_boundary
    assert none_arm.guard == guard
    assert none_arm.faces == frozenset({none_side})
    assert none_arm.owed == ("debt:none",)
    assert pattern_arm.value is pattern_boundary
    assert pattern_arm.guard == complement_guard(guard)
    assert pattern_arm.faces == frozenset({pattern_side})
    assert pattern_arm.owed == ("debt:pattern",)


def test_a_spread_application_keeps_the_call_arms_testimony() -> None:
    # The application was rebuilt as a fresh truth arm owing the call's
    # debts: the call arm's partition testimony was dropped.
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.outcome.exit_set import true_guard
    from sugar_lift_python_source.manager_summary_derivation import (
        _constructor_application_from_spread,
    )

    class _BoundCall(CallSiteValue):
        """A constructor call whose actuals are already bound."""

        __eq__ = object.__eq__
        __hash__ = object.__hash__
        bound_source_actuals = SimpleNamespace(actuals=(TermValue(1),))

    call = object.__new__(_BoundCall)
    side, _other = partition(("test:spread-call", 7825))
    outcome = ExitSet(
        (Completed(true_guard(), call, frozenset({side}), ("debt:call",)),)
    )
    call_sugar = SimpleNamespace(
        desugar=lambda ctx: outcome,
        source_call_frame=SimpleNamespace(
            parameters=("expected",),
            parameter_kinds=("positional_or_keyword",),
        ),
        site="test:spread-site:7825",
        call_occurrence=None,
    )

    (arm,) = _constructor_application_from_spread(call_sugar, None).exits

    assert isinstance(arm, Completed)
    assert arm.value.arguments == (TermValue(1),)
    assert arm.value.keyword_names == ()
    assert arm.guard == true_guard()
    assert arm.faces == frozenset({side})
    assert arm.owed == ("debt:call",)
