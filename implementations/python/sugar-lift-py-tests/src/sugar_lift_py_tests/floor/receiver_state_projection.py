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
