"""Cut D: construct source-visible context-manager protocol methods once."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    EnteredManagerStateValue,
    GuardedReceiverFieldStoreValue,
    ObjectField,
    ObjectValue,
    ReceiverFieldStoreValue,
    ReceiverStatePartitionValue,
)
from sugar_lift_py_tests.floor.manager_coordinate import (
    ExitTracebackCoordinate,
    ExitTypeCoordinate,
    ExitValueCoordinate,
)
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

from .canonical import cid_of_json
from .manager_construction import ConstructedManagerBehaviorV1


@dataclass(frozen=True)
class ConstructedManagerProtocolV1:
    manager_construction_cid: str
    protocol_construction_cid: str
    enter_call: CallSiteValue = field(compare=False)
    exit_call: CallSiteValue = field(compare=False)
    enter_frame_cid: str
    exit_frame_cid: str
    exit_face_id: str
    receiver_state: ObjectValue | ReceiverStatePartitionValue = field(compare=False)

    @property
    def preimage(self):
        return {
            "kind": "constructed-manager-protocol",
            "schemaVersion": "1",
            "managerConstructionCid": self.manager_construction_cid,
            "enterFrameCid": self.enter_frame_cid,
            "exitFrameCid": self.exit_frame_cid,
            "exitFaceId": self.exit_face_id,
        }

    def __post_init__(self) -> None:
        if cid_of_json(self.preimage) != self.protocol_construction_cid:
            raise ValueError("manager protocol CID does not match its preimage")

    def at_exit_face(self, exit_face_id: str) -> "ConstructedManagerProtocolV1":
        """This protocol describing ``__exit__`` over ``exit_face_id``.

        The same receiver and the same protocol method frames; only the exit
        face the calls are bound over (and so the protocol's construction
        CID) is the given one: one face per evaluation of a duplicated
        ``with`` (``WithItem._exit_face_id``)."""
        enter, exit_ = _protocol_calls_at_face(
            _completed_object_receivers(self.receiver_state)[0], exit_face_id
        )
        return ConstructedManagerProtocolV1(
            self.manager_construction_cid,
            cid_of_json({**self.preimage, "exitFaceId": exit_face_id}),
            enter,
            exit_,
            self.enter_frame_cid,
            self.exit_frame_cid,
            exit_face_id,
            self.receiver_state,
        )

    def enter_outcome(self, ctx: object = None):
        if isinstance(self.receiver_state, ObjectValue):
            return _apply_protocol_call(self.enter_call, ctx)
        # Beneath one of several receiver faces the enter is sequenced, which
        # reads its arms: a deferred carrier there is refused by name.
        return _completed_receiver_exits(self.receiver_state).sequence(
            lambda receiver: _require_exit_set(
                _call_protocol_method(
                    receiver,
                    "__enter__",
                    (),
                    self.exit_face_id,
                    ctx,
                ),
                owner="ConstructedManagerProtocolV1.enter_outcome",
            )
        )

    def exit_outcome(self, ctx: object = None):
        def run_exit(receiver):
            enter = _call_protocol_method(
                receiver, "__enter__", (), self.exit_face_id, ctx
            )
            entered = _receiver_state_after_enter(
                receiver, enter, blame=self.exit_face_id
            )
            return _call_protocol_method(
                entered,
                "__exit__",
                (
                    ExitTypeCoordinate(self.exit_face_id, None),
                    ExitValueCoordinate(self.exit_face_id, None),
                    ExitTracebackCoordinate(self.exit_face_id, None),
                ),
                self.exit_face_id,
                ctx,
            )

        if isinstance(self.receiver_state, ObjectValue):
            return run_exit(self.receiver_state)
        # Beneath one of several receiver faces the exit is sequenced: only
        # the one-receiver exit above hands a deferred carrier on.
        return _completed_receiver_exits(self.receiver_state).sequence(
            lambda receiver: _require_exit_set(
                run_exit(receiver), owner="ConstructedManagerProtocolV1.exit_outcome"
            )
        )

    def enter_resource_outcome(self, ctx: object = None):
        """Run enter once and carry each face's exact receiver into resource exit."""
        if isinstance(self.receiver_state, ObjectValue):
            return self.enter_resource_outcome_for(self.receiver_state, ctx)
        return _completed_receiver_exits(self.receiver_state).sequence(
            lambda receiver: self.enter_resource_outcome_for(receiver, ctx)
        )

    def enter_resource_outcome_for(self, receiver, ctx: object = None):
        """Run enter on the exact receiver value produced by the manager face."""
        enter = _call_protocol_method(receiver, "__enter__", (), self.exit_face_id, ctx)
        return _resource_enter_transitions(receiver, enter, blame=self.exit_face_id)

    def exit_outcome_for(self, entered: EnteredManagerStateValue, ctx: object = None):
        if not isinstance(entered, EnteredManagerStateValue):
            # Naked TypeError(type(entered).__name__) named neither the door nor
            # the artifact we need — instrument noise on the board.
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                blame=self.exit_face_id,
                owner="ManagerProtocol.exit_outcome_for",
                observed=(
                    f"exit_outcome_for received {type(entered).__name__}, not "
                    f"EnteredManagerStateValue"
                ),
                requested="EnteredManagerStateValue from the matching enter face",
                fix=(
                    "carry enter's EnteredManagerStateValue into exit; do not "
                    "raise bare TypeError with only the type name"
                ),
            )
        return _call_protocol_method(
            entered.receiver_state,
            "__exit__",
            (
                ExitTypeCoordinate(self.exit_face_id, None),
                ExitValueCoordinate(self.exit_face_id, None),
                ExitTracebackCoordinate(self.exit_face_id, None),
            ),
            self.exit_face_id,
            ctx,
        )

    def exit_outcome_for_body(self, entered, body_face, ctx: object = None):
        """Invoke the cited exit frame with this body face's actual ABI inputs.

        Python language reference 8.5, the with statement:
        https://docs.python.org/3/reference/compound_stmts.html#the-with-statement

        Bind before reducing the native method, not after an abstract reduction:
        unreachable normal/exceptional branches must not perform field lookups.
        """
        from sugar_lift_py_tests.outcome import Completed, Halted
        from sugar_lift_py_tests.effect import GroupedRaiseEffect, RaiseEffect
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.floor.undetermined_exception_value import (
            UndeterminedExceptionTypeValue,
        )
        from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
        from sugar_lift_py_tests.floor import FloorValue, NoneValue
        from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
            AuthenticatedExceptionTypeValue,
        )
        from sugar_lift_py_tests.floor.manager_coordinate import RaisedExitTypeValue
        from sugar_lift_py_tests.floor.class_value import ClassValue
        from sugar_lift_py_tests.floor.class_definition_value import (
            ClassDefinitionValue,
        )
        from sugar_lift_py_tests.floor.exception_class_value import ExceptionClassValue
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        if not isinstance(entered, EnteredManagerStateValue):
            construction_panic_gap(
                owner="ManagerProtocol.exit_outcome_for_body",
                blame=self.exit_face_id,
                observed=type(entered).__name__,
                requested="matching entered manager state",
                fix="carry the exact enter face into resource exit",
            )
        if isinstance(body_face, Completed) or (
            isinstance(body_face, Halted)
            and isinstance(body_face.effect, LoopControlEffect)
        ):
            args = (NoneValue(), NoneValue(), NoneValue())
        elif isinstance(body_face, Halted) and isinstance(
            body_face.effect, RaiseEffect
        ):
            effect = body_face.effect
            value = effect.raised_value
            # The RaiseEffect already owns type identity. Pass the native value,
            # not that identity witness, into the callee's operation dispatch.
            while isinstance(value, AuthenticatedExceptionTypeValue):
                value = value.value
            if value is None or isinstance(
                value, (ClassValue, ClassDefinitionValue, ExceptionClassValue)
            ):
                # A bare class still needs native exception instantiation; it
                # must never stand in for the actual instance supplied by With.
                # The raise authenticates an instance's existence, not its
                # fields. An unused slot needs no fabricated instance; a lookup
                # on this still-undischarged slot remains a typed demand.
                value = ExitValueCoordinate(self.exit_face_id, None)
            if not isinstance(value, FloorValue):
                construction_panic_gap(
                    owner="ManagerProtocol.exit_outcome_for_body",
                    blame=effect.occurrence,
                    observed="authenticated raise without an actual exception value",
                    requested="actual raised Floor value, not a guessed instance",
                    fix="retain the exception producer's actual value on the body face",
                )
            args = (
                RaisedExitTypeValue(
                    effect.exception_type_coordinate, effect.exception_type_mro
                ),
                value,
                ExitTracebackCoordinate(self.exit_face_id, None),
            )
        elif isinstance(body_face, Halted) and isinstance(
            body_face.effect, GroupedRaiseEffect
        ):
            from sugar_lift_py_tests.floor.grouped_exception_value import (
                GroupedExceptionValue,
            )
            from sugar_lift_py_tests.ir import ctor, str_const

            effect = body_face.effect
            # BaseExceptionGroup(...) natively becomes ExceptionGroup when every
            # leaf is an Exception, so only the ExceptionGroup coordinate states
            # the instance's real class.
            if effect.exception_type_coordinate != ctor(
                "python:exception_type_identity",
                [str_const("builtins"), str_const("ExceptionGroup")],
            ) or effect.exception_type_mro is None:
                construction_panic_gap(
                    owner="ManagerProtocol.exit_outcome_for_body",
                    blame=self.exit_face_id,
                    observed="exception group without builtins.ExceptionGroup testimony",
                    requested="an authenticated builtins.ExceptionGroup body raise",
                    fix="authenticate the group's native class before exit inputs",
                )
            args = (
                RaisedExitTypeValue(
                    effect.exception_type_coordinate, effect.exception_type_mro
                ),
                GroupedExceptionValue(effect, self.exit_face_id),
                ExitTracebackCoordinate(self.exit_face_id, None),
            )
        elif isinstance(body_face, Halted) and isinstance(
            body_face.effect, UndeterminedRaiseEffect
        ) and body_face.effect.exception_value is not None:
            # A may-raise operation threw ONE exception object nobody testified
            # to. With hands it to __exit__ like any raise: (type(e), e, tb),
            # with type(e) derived from e itself, never a guessed class. The
            # exit's own type tests then split on it.
            exception = body_face.effect.exception_value
            args = (
                UndeterminedExceptionTypeValue(exception),
                exception,
                ExitTracebackCoordinate(self.exit_face_id, None),
            )
        else:
            construction_panic_gap(
                owner="ManagerProtocol.exit_outcome_for_body",
                blame=self.exit_face_id,
                observed=type(getattr(body_face, "effect", body_face)).__name__,
                requested="normal control or an authenticated raised body face",
                fix="authenticate the body exit before constructing native exit inputs",
            )
        return _call_protocol_method(
            entered.receiver_state,
            "__exit__",
            args,
            self.exit_face_id,
            ctx,
        )


def _completed_object_receivers(receiver) -> tuple[ObjectValue, ...]:
    """Flatten nested constructor partitions to completed ObjectValue faces.

    Dual-mode factories that ground ``isinstance`` / validation branches can
    nest a receiver partition inside an outer Completed face (validation Halted
    sibling + inner completed ObjectValue).  Protocol methods need the ObjectValue
    leaves; nested partitions are not themselves callable receivers.

    Field-store sequencing can also emit intermediate ObjectValue faces that
    hold only a prefix of constructor stores.  Keep only faces that are not
    field-wise strictly refined by another completed face of the same class —
    the same refinement law manager construction uses for multi-arm factories.
    """
    if isinstance(receiver, ObjectValue):
        return (receiver,)
    if not isinstance(receiver, ReceiverStatePartitionValue):
        return ()
    found: list[ObjectValue] = []
    for face in receiver.exits.exits:
        if not isinstance(face, Completed):
            continue
        found.extend(_completed_object_receivers(face.value))
    return _maximal_field_receivers(tuple(found))


def _maximal_field_receivers(
    receivers: tuple[ObjectValue, ...],
) -> tuple[ObjectValue, ...]:
    """Drop intermediate constructor stores refined by a fuller peer face."""
    if len(receivers) <= 1:
        return receivers

    def fields_of(obj: ObjectValue) -> dict[str, object]:
        return {field.name: field.value for field in obj.fields}

    def refines(a: ObjectValue, b: ObjectValue) -> bool:
        if a.class_name != b.class_name:
            return False
        fa, fb = fields_of(a), fields_of(b)
        if not set(fb).issubset(set(fa)):
            return False
        for name, value in fb.items():
            if fa[name] != value:
                return False
        return len(fa) > len(fb)

    kept = []
    for candidate in receivers:
        if any(
            other is not candidate and refines(other, candidate) for other in receivers
        ):
            continue
        kept.append(candidate)
    return tuple(kept)


def _completed_receiver_exits(receiver_state: ReceiverStatePartitionValue):
    """Protocol methods run only after manager construction completed.

    Constructor validation halts remain authenticated in the behavior's
    receiver partition, but they never enter ``__enter__`` or ``__exit__``.
    Each completed face continues as its object receivers beneath itself
    (``ExitSet.sequence``), so every receiver keeps the guard, partition
    testimony and pending contracts of each face on its path. Nested
    partitions (from dual-mode factory validation) are flattened to their
    ObjectValue leaves under the same Completed-only rule: a nested leaf
    holds under its own face's guard conjoined with the enclosing face's,
    exactly where Python reaches it, never under the enclosing guard alone.
    """
    from sugar_lift_py_tests.outcome import ExitSet

    leaves = _completed_object_receivers(receiver_state)
    if not leaves:
        return ExitSet(())

    def protocol_receivers(partition, kept):
        """``partition``'s object receivers, each beneath its face.

        ``kept`` is ``None`` at the top level (every object face stands) and,
        inside a nested partition, the maximal leaves of that nested
        construction (``_completed_object_receivers``)."""

        def receivers(value):
            if isinstance(value, ObjectValue):
                if kept is None or any(value is leaf for leaf in kept):
                    return ExitSet.completed(value)
                return ExitSet(())
            if isinstance(value, ReceiverStatePartitionValue):
                return protocol_receivers(
                    value,
                    _completed_object_receivers(value) if kept is None else kept,
                )
            return ExitSet(())

        # A constructor halt never enters ``__enter__`` or ``__exit__``: no
        # protocol receiver continues beneath it. It stays a face of the
        # behavior's receiver partition, which still carries it.
        return partition.exits.sequence(receivers, consume=lambda _halt: ExitSet(()))

    return protocol_receivers(receiver_state, None)


def _call_protocol_method(receiver, name, arguments, exit_face_id, ctx):
    """``receiver.<name>(*arguments)``: bound, then applied, as every call is.

    The protocol method binds through ``bind_method_call`` (the receiver's
    ``bound_method_call``), so its frame is read again at the module
    execution site the With runs at (#7972), and is applied by
    ``_apply_protocol_call`` (``CallSiteValue.producer_outcome``).
    """
    from sugar_source_tree.panic import SugarNotWritten

    bound_method_call = getattr(receiver, "bound_method_call", None)
    if not callable(bound_method_call):
        raise SugarNotWritten(
            blame=exit_face_id,
            owner="ConstructedManagerProtocolV1.protocol_method",
            observed=type(receiver).__name__,
            requested=f"authenticated {name} call over projected receiver state",
            fix="preserve the exact receiver method frame or keep protocol loud",
        )
    return _apply_protocol_call(
        bound_method_call(
            name,
            arguments,
            owner="ConstructedManagerProtocolV1.protocol_method",
            blame=exit_face_id,
            ctx=ctx,
        ),
        ctx,
    )


def _apply_protocol_call(call: CallSiteValue, ctx):
    """The one application of a bound ``__enter__``/``__exit__`` call.

    ``CallSiteValue.producer_outcome`` applies it, as it applies every call
    (#7757 entry 6, #7969): each halt of the body is the call's own, and a
    deferred native operation over a formal is discharged against the bound
    actuals.  The With reads what the body did (its receiver stores and its
    return), so each completed face carries the body completion the Call
    retained (``retained_source_completion_outcome``), never a second
    reduction of the body.
    """
    from sugar_lift_py_tests.gap.panic import construction_panic_gap
    from sugar_lift_py_tests.outcome import ExitSet

    if call.body is None:
        # ``producer_outcome`` answers a bodiless call with the call itself;
        # a protocol method with no source body stays the refusal it was.
        construction_panic_gap(
            owner="ConstructedManagerProtocolV1.protocol_method",
            blame=call.target_name,
            observed="protocol method call has no source body",
            requested="the constructed source body of the protocol method",
            fix="retain the source-visible call frame or keep the call loud",
        )
    outcome = call.producer_outcome(ctx)
    if not isinstance(outcome, ExitSet):
        return outcome

    def body_completion(value):
        # Each completed face continues as the body completion it retained
        # (``ExitSet.sequence``): its guard, faces and ``owed`` ride on. Each
        # halt of the body stands as the call's own.
        if isinstance(value, CallSiteValue) and value.term is call.term:
            retained = value.retained_source_completion_outcome()
            if retained is not None:
                return ExitSet.completed(retained.completed_value())
        return ExitSet.completed(value)

    return outcome.sequence(body_completion)


def _receiver_state_after_enter(
    receiver: ObjectValue, enter_outcome, *, blame: object
) -> ObjectValue:
    from sugar_lift_py_tests.outcome import Completed
    from sugar_source_tree.panic import SugarNotWritten

    # The post-enter receiver is read off the enter's faces: an enter that is
    # a deferred native-operation carrier is refused by name.
    exits = _require_exit_set(
        enter_outcome,
        owner="ConstructedManagerProtocolV1.receiver_state_after_enter",
    ).exits
    completed = tuple(face for face in exits if isinstance(face, Completed))
    observed_stores = tuple(
        statement
        for face in completed
        if isinstance(face.value, BlockValue)
        for statement in face.value.statements
        if isinstance(statement, ReceiverFieldStoreValue)
    )
    if not observed_stores:
        return receiver
    # __exit__ runs only after __enter__ returned: a halted enter face leaves
    # the With as itself and never reaches exit, so the post-enter state is
    # projected from the completed faces alone.
    if not completed:
        raise SugarNotWritten(
            blame=blame,
            owner="ConstructedManagerProtocolV1.receiver_state_after_enter",
            observed="no completed __enter__ face",
            requested="a completed enter face before __exit__",
            fix="derive exit state only from an authenticated enter face that completes",
        )
    projected_faces = []
    for face in completed:
        block = face.value
        if not isinstance(block, BlockValue):
            raise SugarNotWritten(
                blame=blame,
                owner="ConstructedManagerProtocolV1.receiver_state_after_enter",
                observed=type(block).__name__,
                requested="completed enter block carrying exact receiver stores",
                fix="preserve the ordinary enter block or keep receiver state loud",
            )
        fields = {field.name: field.value for field in receiver.fields}
        for statement in block.statements:
            if not isinstance(statement, ReceiverFieldStoreValue):
                continue
            if statement.receiver.identity != receiver.identity:
                raise SugarNotWritten(
                    blame=blame,
                    owner="ConstructedManagerProtocolV1.receiver_state_after_enter",
                    observed="receiver coordinate mismatch",
                    requested="stores from the exact authenticated manager receiver",
                    fix="preserve ObjectValue.identity across protocol method binding",
                )
            fields[statement.attr] = statement.value
        projected_faces.append(
            tuple(ObjectField(name, fields[name]) for name in sorted(fields))
        )
    first = projected_faces[0]
    if any(fields != first for fields in projected_faces[1:]):
        raise SugarNotWritten(
            blame=blame,
            owner="ConstructedManagerProtocolV1.receiver_state_after_enter",
            observed="guarded enter faces disagree on receiver fields",
            requested="one exact post-enter ObjectValue.fields projection",
            fix="carry guarded object-state testimony before reducing __exit__",
        )
    return ObjectValue(
        receiver.class_name,
        first,
        methods=receiver.methods,
        class_fields=receiver.class_fields,
        identity=receiver.identity,
        deferred_helper_fields=receiver.deferred_helper_fields,
        # The same object: it keeps its ``allocation`` and ``arrival``.
        allocation=receiver.allocation,
        arrival=receiver.arrival,
    )


def _resource_enter_transitions(receiver: ObjectValue, enter_outcome, *, blame: object):
    from sugar_lift_py_tests.ir import not_
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import partition
    from sugar_source_tree.panic import SugarNotWritten

    # Each enter face becomes one resource transition: an enter that is a
    # deferred native-operation carrier is refused by name.
    enter_exits = _require_exit_set(
        enter_outcome, owner="ConstructedManagerProtocolV1.resource_enter_transitions"
    )

    def stored(state, statement):
        """The receiver states after one acquisition store, beneath ``state``.

        A guarded store splits the state: each side is one fresh arm
        (``ExitSet.completed``) restricted to its face of the split, and the
        two sides join through the one join."""
        if isinstance(statement, GuardedReceiverFieldStoreValue):
            then_face, else_face = partition(
                ("resource-enter-store", statement.to_term(owner=receiver.identity))
            )
            return (
                ExitSet.completed(_apply_receiver_store(state, statement, blame=blame))
                .guarded(statement.guard, then_face)
                .union(
                    ExitSet.completed(state).guarded(
                        not_(statement.guard), else_face
                    )
                )
            )
        if isinstance(statement, ReceiverFieldStoreValue):
            return ExitSet.completed(
                _apply_receiver_store(state, statement, blame=blame)
            )
        return ExitSet.completed(state)

    def transitions(block):
        if not isinstance(block, BlockValue):
            raise SugarNotWritten(
                blame=blame,
                owner="ConstructedManagerProtocolV1.enter_resource_outcome",
                observed=type(block).__name__,
                requested="completed enter block carrying exact acquisition stores",
                fix="preserve the ordinary enter block or keep resource state loud",
            )
        # Each store runs beneath every state the stores before it reached
        # (``ExitSet.sequence``), so each split's guard and face ride on.
        states = ExitSet.completed(receiver)
        for statement in block.statements:
            states = states.sequence(
                lambda state, statement=statement: stored(state, statement)
            )
        return states.sequence(
            lambda state: ExitSet.completed(EnteredManagerStateValue(block, state))
        )

    # Every transition runs beneath its enter face (``ExitSet.sequence``):
    # the face's guard, faces and ``owed`` ride onto each one. A halted enter
    # face leaves the With as itself.
    return enter_exits.sequence(transitions)


def _apply_receiver_store(
    receiver: ObjectValue, statement: ReceiverFieldStoreValue, *, blame: object
) -> ObjectValue:
    from sugar_source_tree.panic import SugarNotWritten

    if statement.receiver.identity != receiver.identity:
        raise SugarNotWritten(
            blame=blame,
            owner="ConstructedManagerProtocolV1.enter_resource_outcome",
            observed="receiver coordinate mismatch",
            requested="acquisition store from the exact authenticated receiver",
            fix="preserve ObjectValue.identity across the enter transition",
        )
    fields = {field.name: field.value for field in receiver.fields}
    fields[statement.attr] = statement.value
    return ObjectValue(
        receiver.class_name,
        tuple(ObjectField(name, fields[name]) for name in sorted(fields)),
        methods=receiver.methods,
        class_fields=receiver.class_fields,
        identity=receiver.identity,
        # The same object: it keeps its ``allocation`` and ``arrival``.
        allocation=receiver.allocation,
        arrival=receiver.arrival,
    )


@dataclass(frozen=True)
class ManagerProtocolConstructionGapV1:
    kind: Literal[
        "enter-missing",
        "exit-missing",
        "method-construction",
    ]
    manager_construction_cid: str
    detail: str


def construct_manager_protocol(
    behavior: ConstructedManagerBehaviorV1,
    *,
    exit_face_id: str,
) -> ConstructedManagerProtocolV1 | ManagerProtocolConstructionGapV1:
    """Project ``__enter__``/``__exit__`` from Cut C's exact receiver.

    Method bodies were constructed by ``FunctionDef`` and retained by the
    class-construction arm.  This function only binds the constructed receiver
    and the typed exit-face operands to those bodies.
    """
    receiver = behavior.receiver_state
    receivers = _completed_object_receivers(receiver)
    if not receivers:
        return ManagerProtocolConstructionGapV1(
            "method-construction",
            behavior.manager_construction_cid,
            "constructor partition has no completed receiver face",
        )
    # A method the one class-namespace lookup does not decide (``has_method``
    # None) is no source-visible method either.
    if any(item.has_method("__enter__") is not True for item in receivers):
        return ManagerProtocolConstructionGapV1(
            "enter-missing", behavior.manager_construction_cid, "source-visible method"
        )
    if any(item.has_method("__exit__") is not True for item in receivers):
        return ManagerProtocolConstructionGapV1(
            "exit-missing", behavior.manager_construction_cid, "source-visible method"
        )
    representative = receivers[0]
    enter, exit_ = _protocol_calls_at_face(representative, exit_face_id)
    enter_frame_cid = _method_frame_cid(representative, "__enter__")
    exit_frame_cid = _method_frame_cid(representative, "__exit__")
    if any(
        _method_frame_cid(item, "__enter__") != enter_frame_cid
        or _method_frame_cid(item, "__exit__") != exit_frame_cid
        for item in receivers[1:]
    ):
        return ManagerProtocolConstructionGapV1(
            "method-construction",
            behavior.manager_construction_cid,
            "constructor faces disagree on protocol method frames",
        )
    preimage = {
        "kind": "constructed-manager-protocol",
        "schemaVersion": "1",
        "managerConstructionCid": behavior.manager_construction_cid,
        "enterFrameCid": enter_frame_cid,
        "exitFrameCid": exit_frame_cid,
        "exitFaceId": exit_face_id,
    }
    return ConstructedManagerProtocolV1(
        behavior.manager_construction_cid,
        cid_of_json(preimage),
        enter,
        exit_,
        enter_frame_cid,
        exit_frame_cid,
        exit_face_id,
        receiver,
    )


def _protocol_calls_at_face(representative, exit_face_id: str):
    """``__enter__()`` and ``__exit__(ExitTypeRef(X), …)`` bound on the
    representative receiver, with ``X`` the exit face."""
    enter = representative.bound_method_call(
        "__enter__", (), owner="construct_manager_protocol", blame=exit_face_id
    )
    exit_ = representative.bound_method_call(
        "__exit__",
        (
            ExitTypeCoordinate(exit_face_id, None),
            ExitValueCoordinate(exit_face_id, None),
            ExitTracebackCoordinate(exit_face_id, None),
        ),
        owner="construct_manager_protocol",
        blame=exit_face_id,
    )
    return enter, exit_


def _method_frame_cid(receiver, name: str) -> str:
    """The frame of the method the one class-namespace lookup selects for
    ``name`` on the receiver's type (``ObjectValue.class_member``)."""
    _decided, method, _value = receiver.class_member(name)
    if method is None or method.source_call_frame_cid is None:
        raise ValueError("source-visible method has no authenticated call frame")
    return method.source_call_frame_cid
