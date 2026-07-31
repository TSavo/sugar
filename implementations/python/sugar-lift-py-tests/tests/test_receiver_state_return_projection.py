from __future__ import annotations

from sugar_lift_py_tests.floor import (
    BlockValue,
    GuardedReceiverFieldStoreValue,
    MappingObjectValue,
    ReceiverFieldStoreValue,
    ReceiverStatePartitionValue,
    ReturnValue,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.floor.source_return_projection import (
    project_authenticated_source_return,
)
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.ir import atomic


def _receiver(identity: str = "receiver") -> MappingObjectValue:
    return MappingObjectValue("Mapping", (), identity=identity)


def test_exact_returned_alias_gains_every_ordered_receiver_store() -> None:
    receiver = _receiver()
    body = BlockValue(
        (
            ReceiverFieldStoreValue(receiver, "first", TermValue(1)),
            ReceiverFieldStoreValue(receiver, "second", TermValue(2)),
            ReturnValue(receiver),
        ),
        can_fall_through=False,
    )

    projected = project_authenticated_source_return(body)

    assert isinstance(projected, MappingObjectValue)
    assert [(field.name, field.value) for field in projected.fields] == [
        ("first", TermValue(1)),
        ("second", TermValue(2)),
    ]


def test_foreign_receiver_identity_cannot_mutate_returned_alias() -> None:
    returned = _receiver("returned")
    foreign = _receiver("foreign")
    body = BlockValue(
        (
            ReceiverFieldStoreValue(foreign, "invented", StringValue("wrong")),
            ReturnValue(returned),
        ),
        can_fall_through=False,
    )

    projected = project_authenticated_source_return(body)

    assert projected is returned
    assert projected.fields == ()


def test_live_alias_rebind_uses_authenticated_identity_not_host_object() -> None:
    store_receiver = _receiver("shared")
    later_alias = MappingObjectValue(
        "Mapping", (), identity="shared", entries=((StringValue("k"), TermValue(1)),)
    )
    context = ReduceContext.root(owner="test")
    context.temporal = context.temporal.bind_value("alias", later_alias)

    updated = ReceiverFieldStoreValue(
        store_receiver, "field", TermValue(2)
    ).extend_scope(context)

    rebound = updated.temporal.value_if_bound("alias")
    assert rebound is not later_alias
    assert rebound.entries == later_alias.entries
    assert [(field.name, field.value) for field in rebound.fields] == [
        ("field", TermValue(2))
    ]


def test_guarded_receiver_store_remains_a_state_partition() -> None:
    receiver = _receiver()
    body = BlockValue(
        (
            GuardedReceiverFieldStoreValue(
                receiver, "conditional", TermValue(1), atomic("condition", ())
            ),
            ReturnValue(receiver),
        ),
        can_fall_through=False,
    )

    projected = project_authenticated_source_return(body)

    assert isinstance(projected, ReceiverStatePartitionValue)
    assert len(projected.exits.exits) == 2
    assert sorted(len(face.value.fields) for face in projected.exits.exits) == [0, 1]


def test_competing_returns_stay_unprojected_and_loud() -> None:
    receiver = _receiver()
    body = BlockValue(
        (ReturnValue(receiver), ReturnValue(_receiver("other"))),
        can_fall_through=False,
    )

    assert project_authenticated_source_return(body) is body
