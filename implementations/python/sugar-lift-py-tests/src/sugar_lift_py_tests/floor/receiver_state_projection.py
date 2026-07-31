from __future__ import annotations

from .floor_value import FloorValue


def same_authenticated_receiver(left: object, right: object) -> bool:
    """Whether two immutable receiver versions name one authenticated object."""
    from .object_value import ObjectValue

    return (
        isinstance(left, ObjectValue)
        and isinstance(right, ObjectValue)
        and bool(left.identity)
        and left.identity == right.identity
    )


def project_receiver_owned_mutation_chain(
    initial: FloorValue,
    mutations: tuple[object, ...],
    *,
    owner: str,
    blame: object,
):
    """Compose ordered immutable receiver transitions over guarded states.

    A guarded mutation is a relation over one receiver identity, not a foreign
    receiver merely because the partition wrapper has no ``identity`` field.
    Flatten every state to concrete completed faces, sequence each relation
    only from the exact state it names, and leave complementary faces intact.
    The result stays an ExitSet while more than one live receiver state exists;
    callers therefore sequence later operations once per face instead of
    guessing a last-wins receiver.
    """
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.receiver_owned_mutation_result import (
        ReceiverOwnedMutationResult,
    )
    from sugar_lift_py_tests.floor.receiver_state_partition_value import (
        ReceiverStatePartitionValue,
    )
    from sugar_lift_py_tests.gap.panic import construction_panic_gap
    from sugar_lift_py_tests.ir import not_
    from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
    from sugar_lift_py_tests.outcome.exit_set import (
        _and_guards,
        _are_exclusive,
        _complete_family,
        true_guard,
    )

    def loud(observed: str, requested: str, fix: str):
        construction_panic_gap(
            owner=owner,
            blame=blame,
            observed=observed,
            requested=requested,
            fix=fix,
        )

    if not mutations:
        loud(
            "empty receiver-owned mutation chain",
            "nonempty ordered receiver transition chain",
            "preserve the source mutation or keep the operation loud",
        )

    def flatten(value: FloorValue, guard=None) -> ExitSet:
        guard = true_guard() if guard is None else guard
        if isinstance(value, GuardedValue):
            yes = flatten(value.when_true, _and_guards(guard, value.guard))
            no = flatten(value.when_false, _and_guards(guard, not_(value.guard)))
            return ExitSet((*yes.exits, *no.exits)).normalize()
        if isinstance(value, ReceiverStatePartitionValue):
            exits = value.exits.normalize()
            completed = tuple(face for face in exits.exits if isinstance(face, Completed))
            if len(completed) != len(exits.exits):
                loud(
                    "receiver state partition contains a halted face",
                    "completed receiver states for one mutation relation",
                    "route the halt in the exit algebra before receiver projection",
                )
            if len(completed) == 1:
                if completed[0].guard != true_guard():
                    loud(
                        "receiver state partition is not exhaustive",
                        "one unconditional state or a complete guarded family",
                        "retain the producer-owned complementary face",
                    )
            elif not _complete_family(completed) or any(
                not _are_exclusive(left.guard, right.guard)
                for index, left in enumerate(completed)
                for right in completed[index + 1 :]
            ):
                loud(
                    "receiver state arms are not one complementary partition",
                    "producer-authenticated exhaustive and exclusive receiver faces",
                    "retain the exact partition faces and complementary guards",
                )
            return ExitSet(
                tuple(
                    Completed(
                        _and_guards(guard, face.guard),
                        face.value,
                        face.faces,
                        face.pending_contracts,
                    )
                    for face in completed
                )
            ).normalize()
        return ExitSet((Completed(guard, value),)).normalize()

    def validate_live(exits: ExitSet, *, position: int, role: str) -> ExitSet:
        normalized = exits.normalize()
        for face in normalized.exits:
            if isinstance(face, Halted):
                loud(
                    f"halted receiver {role} at position {position}",
                    "completed receiver states inside a mutation relation",
                    "route exceptional control before receiver-state composition",
                )
            value = face.value
            if type(value) is not type(initial) or not same_authenticated_receiver(
                initial, value
            ):
                loud(
                    f"foreign receiver {role} at position {position}: "
                    f"{type(value).__name__}:{getattr(value, 'identity', None)!r}",
                    "same-type, same-identity receiver on every live face",
                    "preserve the source receiver identity; never select by last write",
                )
        return normalized

    current = validate_live(flatten(initial), position=-1, role="initial")
    for position, mutation in enumerate(mutations):
        if not isinstance(mutation, ReceiverOwnedMutationResult):
            loud(
                f"non-mutation entry at position {position}: {type(mutation).__name__}",
                "ReceiverOwnedMutationResult entries",
                "retain only the source-owned receiver transitions",
            )
        if not isinstance(mutation.result, NoneValue):
            loud(
                f"receiver mutation result at position {position} is "
                f"{type(mutation.result).__name__}",
                "NoneValue as the Python assignment result",
                "keep receiver-after state separate from the statement result",
            )
        before = validate_live(
            flatten(mutation.receiver_before), position=position, role="before"
        )
        after = validate_live(
            flatten(mutation.receiver_after), position=position, role="after"
        )

        current_signature = tuple((face.guard, face.value) for face in current.exits)
        before_signature = tuple((face.guard, face.value) for face in before.exits)
        if current_signature == before_signature:
            current_provenance = tuple(
                (face.faces, face.pending_contracts) for face in current.exits
            )
            before_provenance = tuple(
                (face.faces, face.pending_contracts) for face in before.exits
            )
            if current_provenance != before_provenance:
                loud(
                    f"foreign receiver partition provenance at position {position}",
                    "receiver_before carrying the exact current faces and obligations",
                    (
                        "retain the producer-owned partition relation; equal guards and "
                        "values cannot authorize dropping its testimony"
                    ),
                )
            current = validate_live(
                ExitSet(
                    tuple(
                        Completed(
                            _and_guards(face.guard, following.guard),
                            following.value,
                            face.faces | following.faces,
                            (*face.pending_contracts, *following.pending_contracts),
                        )
                        for face in current.exits
                        for following in after.exits
                    )
                ).normalize(),
                position=position,
                role="composed",
            )
            continue
        if len(before.exits) != 1 or before.exits[0].guard != true_guard():
            loud(
                f"broken receiver mutation chain at position {position}",
                "the exact current partition or one concrete state on a live face",
                "preserve source order and the transition's receiver_before",
            )
        expected = before.exits[0].value
        matched = False
        next_faces = []
        for face in current.exits:
            if face.value != expected:
                next_faces.append(face)
                continue
            matched = True
            next_faces.extend(
                Completed(
                    _and_guards(face.guard, following.guard),
                    following.value,
                    face.faces | following.faces,
                    (*face.pending_contracts, *following.pending_contracts),
                )
                for following in after.exits
            )
        if not matched:
            loud(
                f"broken receiver mutation chain at position {position}",
                "receiver_before equal one exact current state",
                "preserve source order; never apply a competing or reordered transition",
            )
        current = validate_live(
            ExitSet(tuple(next_faces)).normalize(), position=position, role="composed"
        )

    if (
        len(current.exits) == 1
        and isinstance(current.exits[0], Completed)
        and current.exits[0].guard == true_guard()
    ):
        return Complete(current.exits[0].value)
    return current


def fold_receiver_owned_stores(
    returned: FloorValue, stores: tuple[object, ...]
) -> FloorValue:
    """Apply ordered receiver-store testimony to its exact returned alias.

    Immutable receiver versions share the construction-owned ``identity``.
    Stores for any other identity are testimony about another object and are
    deliberately ignored. Guarded stores remain an explicit state partition.
    """
    state = returned
    for store in stores:
        state = _apply_store(state, store)
    return state


def _apply_store(state: FloorValue, store: object) -> FloorValue:
    from .guarded_receiver_field_store_value import GuardedReceiverFieldStoreValue
    from .object_value import ObjectValue
    from .receiver_field_store_value import ReceiverFieldStoreValue
    from .receiver_state_partition_value import ReceiverStatePartitionValue
    from sugar_lift_py_tests.ir import and_, not_
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
    from sugar_lift_py_tests.outcome.exit_set import partition, true_guard

    if not isinstance(store, ReceiverFieldStoreValue):
        return state

    if isinstance(state, ReceiverStatePartitionValue):
        incoming = state.exits.exits
    elif isinstance(state, ObjectValue):
        incoming = (Completed(true_guard(), state),)
    else:
        return state

    changed = False
    exits = []
    for face in incoming:
        if isinstance(face, Halted) or not isinstance(face.value, ObjectValue):
            exits.append(face)
            continue
        receiver = face.value
        if not same_authenticated_receiver(receiver, store.receiver):
            exits.append(face)
            continue
        changed = True
        updated = receiver.with_field_store(store.attr, store.value)
        if isinstance(store, GuardedReceiverFieldStoreValue):
            yes, no = partition(("receiver-field-store", store.to_term(owner=receiver.identity)))
            exits.extend(
                (
                    Completed(
                        and_([face.guard, store.guard]),
                        updated,
                        face.faces | {yes},
                        face.pending_contracts,
                    ),
                    Completed(
                        and_([face.guard, not_(store.guard)]),
                        receiver,
                        face.faces | {no},
                        face.pending_contracts,
                    ),
                )
            )
        else:
            exits.append(
                Completed(
                    face.guard,
                    updated,
                    face.faces,
                    face.pending_contracts,
                )
            )
    if not changed:
        return state
    normalized = ExitSet(tuple(exits)).normalize()
    if (
        len(normalized.exits) == 1
        and isinstance(normalized.exits[0], Completed)
        and normalized.exits[0].guard == true_guard()
    ):
        return normalized.exits[0].value
    return ReceiverStatePartitionValue(normalized)
