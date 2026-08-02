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

        return _completed_receiver_exits(self.receiver_state).sequence(
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
            ).reduce_source_outcome(ctx)

        if isinstance(self.receiver_state, ObjectValue):
            return run_exit(self.receiver_state)
        from sugar_lift_py_tests.outcome import outcome_to_exitset

        return _completed_receiver_exits(self.receiver_state).sequence(
            lambda receiver: outcome_to_exitset(run_exit(receiver))
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
        enter = _call_protocol_method(
            receiver, "__enter__", (), self.exit_face_id, ctx
        ).reduce_source_outcome(ctx)
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
        ).reduce_source_outcome(ctx)


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
    Filtering to native Completed object faces preserves each face's guard,
    partition testimony, and pending contracts without reconstructing them.
    Nested partitions (from dual-mode factory validation) are flattened to
    their ObjectValue leaves under the same Completed-only rule.
    """
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    leaves = _completed_object_receivers(receiver_state)
    if not leaves:
        return ExitSet(())
    # Rebuild Completed faces over the flattened ObjectValue leaves so sequence
    # still walks ordinary receivers. Outer partition guards are recovered
    # when the leaf sits directly under a Completed face; nested leaves keep
    # true_guard (the outer face already admitted them).
    faces = []
    for face in receiver_state.exits.exits:
        if not isinstance(face, Completed):
            continue
        if isinstance(face.value, ObjectValue):
            faces.append(face)
            continue
        if isinstance(face.value, ReceiverStatePartitionValue):
            for leaf in _completed_object_receivers(face.value):
                faces.append(Completed(face.guard, leaf))
    return ExitSet(tuple(faces))


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
            blame=exit_face_id,
            owner="ConstructedManagerProtocolV1.protocol_method",
            observed=type(call).__name__,
            requested=f"authenticated {name} call over projected receiver state",
            fix="preserve the exact receiver method frame or keep protocol loud",
        )
    return call.value


def _receiver_state_after_enter(
    receiver: ObjectValue, enter_outcome, *, blame: object
) -> ObjectValue:
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
            blame=blame,
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
    )


def _resource_enter_transitions(receiver: ObjectValue, enter_outcome, *, blame: object):
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
                blame=blame,
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
                            _apply_receiver_store(state, statement, blame=blame),
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
                    (
                        guard,
                        _apply_receiver_store(state, statement, blame=blame),
                        faces,
                    )
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
    )


@dataclass(frozen=True)
class ManagerProtocolConstructionGapV1:
    kind: Literal[
        "enter-missing",
        "exit-missing",
        "method-construction",
        "generator-missing",
        "generator-protocol",
    ]
    manager_construction_cid: str
    detail: str


@dataclass(frozen=True)
class EnteredGeneratorManagerStateV1:
    """Exact generator suspension after authenticated enter (first yield).

    Carries the yielded resource value and the suspended machine. Exit must
    resume/throw this machine — never a re-allocated twin. Bound to the
    protocol construction CID so a wrong-face resume refuses.
    """

    enter_value: object
    machine: object = field(compare=False, repr=False)
    protocol_construction_cid: str
    entry_cid: str

    def __post_init__(self) -> None:
        if not self.protocol_construction_cid.startswith("blake3-512:"):
            raise ValueError(
                "entered generator state requires protocol construction CID"
            )
        if not self.entry_cid.startswith("blake3-512:"):
            raise ValueError("entered generator state requires entry CID")
        suspended = getattr(self.machine, "suspended_resume_coordinate", None)
        if suspended is None:
            raise ValueError(
                "entered generator state requires a machine suspended at yield"
            )


@dataclass(frozen=True)
class GeneratorBackedManagerProtocolV1:
    """Closed protocol testimony for authenticated generator managers.

    Generator lifecycle lives in the source-visible call frame
    (``generator_steps``). Enter/exit definition coordinates are the
    authenticated method spans of the decorator helper's returned class.
    This is not an ObjectValue receiver and cannot be minted from coordinates
    alone or from a non-generator frame.

    Lifecycle performance: :meth:`enter_resource_outcome` runs the generator
    to its first yield and returns the resource with exact machine state;
    :meth:`exit_outcome_for` resumes/throws that state once and exposes
    authenticated suppression testimony.
    """

    protocol_construction_cid: str
    generator_frame_cid: str
    enter_definition: object
    exit_definition: object
    exit_face_id: str
    generator_frame: object = field(compare=False, repr=False)

    @property
    def preimage(self):
        enter = self.enter_definition
        exit_ = self.exit_definition
        return {
            "kind": "generator-backed-manager-protocol",
            "schemaVersion": "1",
            "generatorFrameCid": self.generator_frame_cid,
            "enterDefinition": enter.wire(),
            "exitDefinition": exit_.wire(),
            "exitFaceId": self.exit_face_id,
        }

    def __post_init__(self) -> None:
        frame = self.generator_frame
        if frame is None:
            raise ValueError(
                "generator-backed protocol requires a source-visible frame"
            )
        if getattr(frame, "generator_steps", None) is None:
            raise ValueError(
                "non-generator frame cannot acquire generator-backed protocol semantics"
            )
        if getattr(frame, "frame_cid", None) != self.generator_frame_cid:
            raise ValueError("generator frame CID does not match protocol testimony")
        if self.enter_definition == self.exit_definition:
            raise ValueError("generator enter/exit definition coordinates must differ")
        if cid_of_json(self.preimage) != self.protocol_construction_cid:
            raise ValueError(
                "generator-backed protocol CID does not match its preimage"
            )
        # One-shot exit log + enter ordinal for this protocol instance.
        object.__setattr__(self, "_exited_entry_cids", set())
        object.__setattr__(self, "_enter_ordinal", 0)

    def enter_resource_outcome(self, ctx: object = None):
        """Enter the authenticated generator lifecycle; return yield + machine."""
        return enter_generator_resource_outcome(self, ctx=ctx)

    def enter_resource_outcome_for(self, machine, ctx: object = None):
        """Enter the exact generator construction returned by the manager call."""
        return enter_bound_generator_resource_outcome(self, machine, ctx=ctx)

    def exit_outcome_for(self, entered, ctx: object = None):
        """Resume/throw the exact entered machine once; expose suppression."""
        return exit_generator_resource_outcome_for(self, entered, ctx=ctx)


def enter_generator_resource_outcome(protocol, *, ctx: object = None):
    """Allocate and resume the generator frame to its first yield.

    Shared by :class:`GeneratorBackedManagerProtocolV1` and lifecycle wrappers
    that duck-type the same fields. Returns ``Complete(EnteredGeneratorManagerStateV1)``
    on yield; typed-loud refusal when the machine cannot enter.
    """
    from sugar_lift_py_tests.generator_construction import (
        GeneratorConstructionV1,
    )
    from sugar_source_tree.panic import SugarNotWritten

    frame = protocol.generator_frame
    steps = getattr(frame, "generator_steps", None)
    if steps is None:
        raise SugarNotWritten(
            blame=protocol.exit_face_id,
            owner="GeneratorBackedManagerProtocolV1.enter_resource_outcome",
            observed="non-generator frame",
            requested="authenticated generator_steps on the protocol frame",
            fix="publish a generator-backed protocol or keep enter loud",
        )
    bindings = tuple(getattr(frame, "runtime_entries", ()) or ())
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate=protocol.protocol_construction_cid,
        frame_coordinate=protocol.generator_frame_cid,
        binding_state=bindings,
        steps=steps,
    )
    return enter_bound_generator_resource_outcome(protocol, machine, ctx=ctx)


def enter_bound_generator_resource_outcome(
    protocol, machine, *, ctx: object = None
):
    """Resume the exact authenticated generator construction at manager enter."""
    del ctx
    from sugar_lift_py_tests.generator_construction import (
        GeneratorConstructionV1,
    )
    from sugar_source_tree.panic import SugarNotWritten

    if type(machine) is not GeneratorConstructionV1:
        raise SugarNotWritten(
            blame=protocol.exit_face_id,
            owner="GeneratorBackedManagerProtocolV1.enter_resource_outcome_for",
            observed=f"foreign construction type {type(machine).__name__}",
            requested="exact GeneratorConstructionV1 from the manager call",
            fix="pass the manager call's authenticated generator construction",
        )
    if machine.frame_coordinate != protocol.generator_frame_cid:
        raise SugarNotWritten(
            blame=protocol.exit_face_id,
            owner="GeneratorBackedManagerProtocolV1.enter_resource_outcome_for",
            observed=f"foreign frame coordinate {machine.frame_coordinate}",
            requested=(
                "exact generator construction frame coordinate "
                f"{protocol.generator_frame_cid}"
            ),
            fix="pass the manager call's authenticated generator construction",
        )
    return _project_generator_enter_result(protocol, machine, machine.resume())


def _project_generator_enter_result(protocol, machine, result):
    """Project one completed resume value into the existing enter state law."""
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.generator_construction import (
        GeneratorConstructionV1,
        GeneratorTerminationV1,
        GeneratorTransitionGapV1,
        YieldEffect,
    )
    from sugar_lift_py_tests.ir import not_
    from sugar_lift_py_tests.outcome import Complete, ExitSet, outcome_to_exitset
    from sugar_source_tree.panic import SugarNotWritten

    if isinstance(result, ExitSet):
        return result.and_then(
            lambda value: _project_generator_enter_result(protocol, machine, value)
        )
    if isinstance(result, GuardedValue):
        def project_arm(arm):
            if type(arm) is GeneratorConstructionV1:
                if arm.frame_coordinate != protocol.generator_frame_cid:
                    raise SugarNotWritten(
                        blame=protocol.exit_face_id,
                        owner="GeneratorBackedManagerProtocolV1.enter_resource_outcome",
                        observed=(
                            "guarded branch machine has foreign frame coordinate "
                            f"{arm.frame_coordinate}"
                        ),
                        requested=(
                            "exact guarded GeneratorConstructionV1 frame coordinate "
                            f"{protocol.generator_frame_cid}"
                        ),
                        fix="retain the authenticated branch machine from transition",
                    )
                return _project_generator_enter_result(protocol, arm, arm.resume())
            return _project_generator_enter_result(protocol, machine, arm)

        return outcome_to_exitset(project_arm(result.when_true)).guarded(
            result.guard
        ).union(
            outcome_to_exitset(project_arm(result.when_false)).guarded(
                not_(result.guard)
            )
        )
    if isinstance(result, YieldEffect):
        enter_value = _floor_enter_value(result.value)
        # Per-protocol enter ordinal distinguishes successive enters that
        # content-address to the same machine suspension (double-exit is
        # per entry, not per content twin).
        ordinal = int(getattr(protocol, "_enter_ordinal", 0))
        object.__setattr__(protocol, "_enter_ordinal", ordinal + 1)
        entry_cid = cid_of_json(
            {
                "kind": "generator-resource-entry",
                "schemaVersion": "1",
                "protocolConstructionCid": protocol.protocol_construction_cid,
                "instanceCoordinate": result.machine.instance_coordinate,
                "resumeCoordinate": result.resume_coordinate,
                "cursor": result.machine.cursor,
                "enterOrdinal": ordinal,
            }
        )
        entered = EnteredGeneratorManagerStateV1(
            enter_value=enter_value,
            machine=result.machine,
            protocol_construction_cid=protocol.protocol_construction_cid,
            entry_cid=entry_cid,
        )
        return Complete(entered)
    # Nested enter can surface Incomplete (inner raise before yield).
    from sugar_lift_py_tests.outcome import Incomplete

    if isinstance(result, Incomplete):
        return result
    if isinstance(result, GeneratorTerminationV1):
        # Never-yield enter: Python's manager protocol raises at entry.
        from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
        from sugar_lift_py_tests.generator_entry_refusal import observed_entry_refusal
        from sugar_lift_py_tests.outcome import Incomplete

        refusal = observed_entry_refusal()
        blame = str(machine.instance_coordinate)
        return Incomplete(
            RaiseEffect.for_builtin(
                refusal.exception_name,
                blame=blame,
                occurrence=f"generator-entry-refusal:{blame}",
                raised_value=refusal.message,
            )
        )
    if isinstance(result, GeneratorTransitionGapV1):
        raise SugarNotWritten(
            blame=protocol.exit_face_id,
            owner="GeneratorBackedManagerProtocolV1.enter_resource_outcome",
            observed=result.observed,
            requested="first yield of the authenticated generator lifecycle",
            fix="construct the transition or retain this typed loud boundary",
        )
    raise SugarNotWritten(
        blame=protocol.exit_face_id,
        owner="GeneratorBackedManagerProtocolV1.enter_resource_outcome",
        observed=type(result).__name__,
        requested="YieldEffect from GeneratorConstructionV1.resume",
        fix="construct the enter transition or keep enter loud",
    )


def exit_generator_resource_outcome_for(protocol, entered, *, ctx: object = None):
    """Resume/throw the exact entered machine once; return suppression testimony.

    - Wrong protocol / wrong face → refuse.
    - Double exit of the same entry → refuse.
    - Suppression is only the authenticated exit outcome (BlockValue return),
      never a fabricated constant.
    """
    del ctx
    from sugar_lift_py_tests.generator_construction import (
        GeneratorTerminationV1,
        GeneratorTransitionGapV1,
        YieldEffect,
    )
    from sugar_lift_py_tests.outcome import Complete, ExitSet
    from sugar_source_tree.panic import SugarNotWritten

    if not isinstance(entered, EnteredGeneratorManagerStateV1):
        raise SugarNotWritten(
            blame=protocol.exit_face_id,
            owner="GeneratorBackedManagerProtocolV1.exit_outcome_for",
            observed=(
                f"exit_outcome_for received {type(entered).__name__}, not "
                f"EnteredGeneratorManagerStateV1"
            ),
            requested="EnteredGeneratorManagerStateV1 from the matching enter face",
            fix=(
                "carry enter's EnteredGeneratorManagerStateV1 into exit; do not "
                "raise bare TypeError with only the type name"
            ),
        )
    if entered.protocol_construction_cid != protocol.protocol_construction_cid:
        raise SugarNotWritten(
            blame=protocol.exit_face_id,
            owner="GeneratorBackedManagerProtocolV1.exit_outcome_for",
            observed="entered state protocol construction CID mismatch",
            requested="exit of the same protocol that performed enter",
            fix="do not resume a foreign entered generator face",
        )
    exited = getattr(protocol, "_exited_entry_cids", None)
    if exited is None:
        object.__setattr__(protocol, "_exited_entry_cids", set())
        exited = protocol._exited_entry_cids
    if entered.entry_cid in exited:
        raise SugarNotWritten(
            blame=protocol.exit_face_id,
            owner="GeneratorBackedManagerProtocolV1.exit_outcome_for",
            observed="double exit of the same entered generator state",
            requested="at most one exit_outcome_for per enter_resource_outcome",
            fix="consume the entered state once; do not re-exit the same entry",
        )
    machine = entered.machine
    if getattr(machine, "suspended_resume_coordinate", None) is None:
        raise SugarNotWritten(
            blame=protocol.exit_face_id,
            owner="GeneratorBackedManagerProtocolV1.exit_outcome_for",
            observed="entered machine is not suspended at yield",
            requested="exact post-enter suspension from enter_resource_outcome",
            fix="pass the EnteredGeneratorManagerStateV1 from enter without reallocation",
        )
    exited.add(entered.entry_cid)
    # Normal body completion path: resume the suspended machine (send None).
    # Body-raise paths are combined by the consumer via and_exit / throw on
    # the machine; this method exposes the authenticated exit outcome for the
    # resume/close face. Suppression is the returned FloorValue only.
    after = machine.resume()
    if isinstance(after, ExitSet):
        return after
    if isinstance(after, YieldEffect):
        raise SugarNotWritten(
            blame=protocol.exit_face_id,
            owner="GeneratorBackedManagerProtocolV1.exit_outcome_for",
            observed="generator yielded during exit",
            requested="GeneratorTerminationV1 after the resource body",
            fix="construct single-yield generator managers or keep exit loud",
        )
    if isinstance(after, GeneratorTransitionGapV1):
        raise SugarNotWritten(
            blame=protocol.exit_face_id,
            owner="GeneratorBackedManagerProtocolV1.exit_outcome_for",
            observed=after.observed,
            requested="authenticated generator exit transition",
            fix="construct the exit transition or retain this typed loud boundary",
        )
    if not isinstance(after, GeneratorTerminationV1):
        raise SugarNotWritten(
            blame=protocol.exit_face_id,
            owner="GeneratorBackedManagerProtocolV1.exit_outcome_for",
            observed=type(after).__name__,
            requested="GeneratorTerminationV1 from post-yield resume",
            fix="construct the exit transition or keep exit loud",
        )
    # Authenticated suppression: generator CM exit is falsy unless the
    # machine returns an explicit truthy residual (none for ordinary GCM).
    # Never invent True — only the termination's return_value may speak.
    return Complete(_suppression_block(after.return_value))


def _floor_enter_value(value: object):
    """Project a yield payload into FloorValue currency when needed."""
    from sugar_lift_py_tests.floor.floor_value import FloorValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar.sugar_base import Sugar

    if isinstance(value, FloorValue):
        return value
    if isinstance(value, Sugar):
        outcome = value.desugar()
        if isinstance(outcome, Complete):
            return _floor_enter_value(outcome.value)
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            blame="generator-enter-yield",
            owner="GeneratorBackedManagerProtocolV1.enter_resource_outcome",
            observed=type(outcome).__name__,
            requested="Complete FloorValue from yielded sugar",
            fix="construct the yield value or keep enter loud",
        )
    if value is None:
        from sugar_lift_py_tests.floor import NoneValue

        return NoneValue()
    if isinstance(value, (int, float, str, bool)):
        return TermValue(value)
    return TermValue(value)


def _suppression_block(return_value: object):
    """BlockValue carrying the authenticated exit return for suppression truth."""
    from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    if return_value is None:
        # contextlib generator __exit__ returns False on normal StopIteration.
        value: object = TermValue(False)
    elif isinstance(return_value, FloorValue):
        value = return_value
    elif isinstance(return_value, bool):
        value = TermValue(return_value)
    else:
        value = _floor_enter_value(return_value)
    return BlockValue((ReturnValue(value),), can_fall_through=False)


def construct_generator_backed_protocol(
    *,
    frame,
    enter_definition,
    exit_definition,
    exit_face_id: str,
    construction_cid: str,
) -> GeneratorBackedManagerProtocolV1 | ManagerProtocolConstructionGapV1:
    """Mint generator-backed protocol from frame + native enter/exit definitions.

    Refuses when the frame is missing, is not a generator suspension, or when
    enter/exit coordinates are absent or identical. Coordinates alone cannot
    construct this protocol — the generator frame is load-bearing.
    """
    if frame is None:
        return ManagerProtocolConstructionGapV1(
            "generator-missing", construction_cid, "source-visible frame required"
        )
    if getattr(frame, "generator_steps", None) is None:
        return ManagerProtocolConstructionGapV1(
            "generator-missing",
            construction_cid,
            "non-generator frame cannot acquire generator semantics",
        )
    if enter_definition is None or exit_definition is None:
        return ManagerProtocolConstructionGapV1(
            "generator-protocol",
            construction_cid,
            "native enter/exit definition coordinates required",
        )
    if enter_definition == exit_definition:
        return ManagerProtocolConstructionGapV1(
            "generator-protocol",
            construction_cid,
            "enter and exit definition coordinates must be distinct",
        )
    frame_cid = frame.frame_cid
    preimage = {
        "kind": "generator-backed-manager-protocol",
        "schemaVersion": "1",
        "generatorFrameCid": frame_cid,
        "enterDefinition": enter_definition.wire(),
        "exitDefinition": exit_definition.wire(),
        "exitFaceId": exit_face_id,
    }
    try:
        return GeneratorBackedManagerProtocolV1(
            cid_of_json(preimage),
            frame_cid,
            enter_definition,
            exit_definition,
            exit_face_id,
            frame,
        )
    except ValueError as exc:
        return ManagerProtocolConstructionGapV1(
            "generator-protocol", construction_cid, str(exc)
        )


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
