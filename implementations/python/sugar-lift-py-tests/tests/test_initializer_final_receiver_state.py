from __future__ import annotations

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import (
    BlockValue,
    MappingObjectValue,
    ReceiverFieldStoreValue,
    ReceiverStatePartitionValue,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet
from sugar_lift_py_tests.outcome.exit_set import partition
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _definition_value():
    source = "class Mapping(dict):\n    pass\n"
    tree = SourceFile((source, "initializer_state.py", blake3_512_of(source.encode())))
    definition = next(node for node in tree.root.body if isinstance(node, ClassDef))
    context = ReduceContext.root(owner="test")
    return context, definition.sugar().desugar(context).value


def test_constructor_selects_final_authenticated_mapping_receiver_version() -> None:
    context, definition = _definition_value()
    initial = definition.construct_receiver_state_from_block(None, "receiver")
    assert isinstance(initial, MappingObjectValue)
    final = initial.mapping_with_entries(((StringValue("k"), TermValue(1)),))
    final = final.with_field_store("field", TermValue(2))
    final_context = context.with_temporal(
        context.temporal.bind_value("receiver", final)
    )
    block = BlockValue((), final_context=final_context)

    projected = definition.project_initializer_outcome(
        Complete(block), initial, "receiver"
    )

    assert projected.value is final
    assert projected.value.entries == final.entries
    assert projected.value.defining_class is definition


def test_foreign_final_receiver_identity_is_ignored_for_constructor_state() -> None:
    context, definition = _definition_value()
    initial = definition.construct_receiver_state_from_block(None, "receiver")
    foreign = MappingObjectValue("Mapping", (), identity="foreign")
    final_context = context.with_temporal(
        context.temporal.bind_value("receiver", foreign)
    )
    block = BlockValue(
        (ReceiverFieldStoreValue(initial, "truth", TermValue(1)),),
        final_context=final_context,
    )

    projected = definition.project_initializer_outcome(
        Complete(block), initial, "receiver"
    ).value

    assert projected is not foreign
    assert projected.defining_class is definition
    assert [(field.name, field.value) for field in projected.fields] == [
        ("truth", TermValue(1))
    ]


def test_guarded_initializer_final_states_remain_partitioned() -> None:
    context, definition = _definition_value()
    initial = definition.construct_receiver_state_from_block(None, "receiver")
    left = initial.with_field_store("left", TermValue(1))
    right = initial.with_field_store("right", TermValue(2))
    yes, no = partition(("initializer-final-state", initial.identity))
    outcome = ExitSet(
        (
            Completed(
                yes,
                BlockValue(
                    (),
                    final_context=context.with_temporal(
                        context.temporal.bind_value("receiver", left)
                    ),
                ),
            ),
            Completed(
                no,
                BlockValue(
                    (),
                    final_context=context.with_temporal(
                        context.temporal.bind_value("receiver", right)
                    ),
                ),
            ),
        )
    )

    projected = definition.project_initializer_outcome(
        outcome, initial, "receiver"
    ).value

    assert isinstance(projected, ReceiverStatePartitionValue)
    names = {
        face.value.fields[0].name
        for face in projected.exits.exits
        if isinstance(face, Completed)
    }
    assert names == {"left", "right"}
