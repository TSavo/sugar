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
from sugar_lift_py_tests.outcome import Complete, Completed

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

    def enter_outcome(self, ctx: object = None):
        if isinstance(self.receiver_state, ObjectValue):
            return self.enter_call.reduce_source_outcome(ctx)
        from sugar_lift_py_tests.outcome import outcome_to_exitset

        return self.receiver_state.exits.sequence(
            lambda receiver: outcome_to_exitset(
                _call_protocol_method(
                    receiver,
                    "__enter__",
                    (),
                    self.exit_face_id,
                    ctx,
                ).reduce_source_outcome(ctx)
            )
        )

    def exit_outcome(self, ctx: object = None):
        def run_exit(receiver):
            enter = _call_protocol_method(
                receiver, "__enter__", (), self.exit_face_id, ctx
            ).reduce_source_outcome(ctx)
            entered = _receiver_state_after_enter(receiver, enter)
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
            ).reduce_source_outcome(ctx)

        if isinstance(self.receiver_state, ObjectValue):
            return run_exit(self.receiver_state)
        from sugar_lift_py_tests.outcome import outcome_to_exitset

        return self.receiver_state.exits.sequence(
            lambda receiver: outcome_to_exitset(run_exit(receiver))
        )

    def enter_resource_outcome(self, ctx: object = None):
        """Run enter once and carry each face's exact receiver into resource exit."""

        def run_enter(receiver):
            enter = _call_protocol_method(
                receiver, "__enter__", (), self.exit_face_id, ctx
            ).reduce_source_outcome(ctx)
            return _resource_enter_transitions(receiver, enter)

        if isinstance(self.receiver_state, ObjectValue):
            return run_enter(self.receiver_state)
        return self.receiver_state.exits.sequence(run_enter)

    def exit_outcome_for(self, entered: EnteredManagerStateValue, ctx: object = None):
        if not isinstance(entered, EnteredManagerStateValue):
            raise TypeError(type(entered).__name__)
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
        ).reduce_source_outcome(ctx)


def _call_protocol_method(receiver, name, arguments, exit_face_id, ctx):
    from sugar_source_tree.panic import SugarNotWritten

    call = receiver.call_method_value(
        name,
        arguments,
        owner="ConstructedManagerProtocolV1.protocol_method",
        blame=exit_face_id,
        ctx=ctx,
    )
    if not isinstance(call, Complete) or not isinstance(call.value, CallSiteValue):
        raise SugarNotWritten(
            owner="ConstructedManagerProtocolV1.protocol_method",
            observed=type(call).__name__,
            requested=f"authenticated {name} call over projected receiver state",
            fix="preserve the exact receiver method frame or keep protocol loud",
        )
    return call.value


def _receiver_state_after_enter(receiver: ObjectValue, enter_outcome) -> ObjectValue:
    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset
    from sugar_source_tree.panic import SugarNotWritten

    exits = outcome_to_exitset(enter_outcome).exits
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
    if not exits or len(completed) != len(exits):
        raise SugarNotWritten(
            owner="ConstructedManagerProtocolV1.receiver_state_after_enter",
            observed="non-completed __enter__ face",
            requested="total completed enter testimony before __exit__",
            fix="derive exit state only after every authenticated enter face completes",
        )
    projected_faces = []
    for face in completed:
        block = face.value
        if not isinstance(block, BlockValue):
            raise SugarNotWritten(
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
    )


def _resource_enter_transitions(receiver: ObjectValue, enter_outcome):
    from sugar_lift_py_tests.ir import and_, not_
    from sugar_lift_py_tests.outcome import (
        Completed,
        ExitSet,
        Halted,
        outcome_to_exitset,
    )
    from sugar_lift_py_tests.outcome.exit_set import partition
    from sugar_source_tree.panic import SugarNotWritten

    projected = []
    for face in outcome_to_exitset(enter_outcome).exits:
        if isinstance(face, Halted):
            projected.append(face)
            continue
        if not isinstance(face.value, BlockValue):
            raise SugarNotWritten(
                owner="ConstructedManagerProtocolV1.enter_resource_outcome",
                observed=type(face.value).__name__,
                requested="completed enter block carrying exact acquisition stores",
                fix="preserve the ordinary enter block or keep resource state loud",
            )
        states = [(face.guard, receiver, face.faces)]
        for statement in face.value.statements:
            if isinstance(statement, GuardedReceiverFieldStoreValue):
                then_face, else_face = partition(
                    ("resource-enter-store", statement.to_term(owner=receiver.identity))
                )
                next_states = []
                for guard, state, faces in states:
                    next_states.append(
                        (
                            and_([guard, statement.guard]),
                            _apply_receiver_store(state, statement),
                            faces | {then_face},
                        )
                    )
                    next_states.append(
                        (
                            and_([guard, not_(statement.guard)]),
                            state,
                            faces | {else_face},
                        )
                    )
                states = next_states
            elif isinstance(statement, ReceiverFieldStoreValue):
                states = [
                    (guard, _apply_receiver_store(state, statement), faces)
                    for guard, state, faces in states
                ]
        projected.extend(
            Completed(
                guard,
                EnteredManagerStateValue(face.value, state),
                faces,
                face.pending_contracts,
            )
            for guard, state, faces in states
        )
    return ExitSet(tuple(projected)).normalize()


def _apply_receiver_store(
    receiver: ObjectValue, statement: ReceiverFieldStoreValue
) -> ObjectValue:
    from sugar_source_tree.panic import SugarNotWritten

    if statement.receiver.identity != receiver.identity:
        raise SugarNotWritten(
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
    )


@dataclass(frozen=True)
class ManagerProtocolConstructionGapV1:
    kind: Literal["enter-missing", "exit-missing", "method-construction"]
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
    receivers = (
        (receiver,)
        if isinstance(receiver, ObjectValue)
        else tuple(
            face.value
            for face in receiver.exits.exits
            if isinstance(face, Completed) and isinstance(face.value, ObjectValue)
        )
    )
    if not receivers:
        return ManagerProtocolConstructionGapV1(
            "method-construction",
            behavior.manager_construction_cid,
            "constructor partition has no completed receiver face",
        )
    if any(not item.has_method("__enter__") for item in receivers):
        return ManagerProtocolConstructionGapV1(
            "enter-missing", behavior.manager_construction_cid, "source-visible method"
        )
    if any(not item.has_method("__exit__") for item in receivers):
        return ManagerProtocolConstructionGapV1(
            "exit-missing", behavior.manager_construction_cid, "source-visible method"
        )
    representative = receivers[0]
    enter = representative.call_method_value(
        "__enter__", (), owner="construct_manager_protocol", blame=exit_face_id
    )
    exit_ = representative.call_method_value(
        "__exit__",
        (
            ExitTypeCoordinate(exit_face_id, None),
            ExitValueCoordinate(exit_face_id, None),
            ExitTracebackCoordinate(exit_face_id, None),
        ),
        owner="construct_manager_protocol",
        blame=exit_face_id,
    )
    if not isinstance(enter, Complete) or not isinstance(enter.value, CallSiteValue):
        return ManagerProtocolConstructionGapV1(
            "method-construction", behavior.manager_construction_cid, "__enter__"
        )
    if not isinstance(exit_, Complete) or not isinstance(exit_.value, CallSiteValue):
        return ManagerProtocolConstructionGapV1(
            "method-construction", behavior.manager_construction_cid, "__exit__"
        )
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
        enter.value,
        exit_.value,
        enter_frame_cid,
        exit_frame_cid,
        exit_face_id,
        receiver,
    )


def _method_frame_cid(receiver, name: str) -> str:
    method = next(item for item in reversed(receiver.methods) if item.name == name)
    if method.source_call_frame_cid is None:
        raise ValueError("source-visible method has no authenticated call frame")
    return method.source_call_frame_cid
