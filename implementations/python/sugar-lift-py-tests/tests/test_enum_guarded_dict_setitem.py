"""A guarded enum dictionary key retains both authenticated post-states."""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import (
    BuiltinSuperValue,
    GuardedValue,
    MappingObjectValue,
    ReceiverOwnedMutationResult,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.ir import atomic
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


_SOURCE = (
    "class EnumNamespace(dict):\n"
    "    def __setitem__(self, key, value):\n"
    "        super().__setitem__(key, value)\n"
)


def _definition_and_receiver():
    tree = SourceFile(
        (_SOURCE, "enum_guarded_setitem.py", blake3_512_of(_SOURCE.encode()))
    )
    definition_node = next(
        node for node in tree.root.body if isinstance(node, ClassDef)
    )
    definition = definition_node.sugar().desugar(
        ReduceContext.root(owner="enum guarded setitem")
    ).value
    receiver = definition.construct_receiver_state_from_block(
        None, "enum-namespace-receiver"
    )
    assert isinstance(receiver, MappingObjectValue)
    return definition, receiver, definition_node.fragment


def _stored_key(mapping: MappingObjectValue) -> StringValue:
    assert len(mapping.entries) == 1
    key, value = mapping.entries[0]
    assert value == TermValue(7)
    assert isinstance(key, StringValue)
    return key


def _guarded_transition(true_key: str, false_key: str):
    definition, receiver, site = _definition_and_receiver()
    guard = atomic("enum:key-rewrite", [])
    key = GuardedValue(
        guard,
        StringValue(true_key),
        StringValue(false_key),
    )

    outcome = BuiltinSuperValue(definition, receiver).call_method_value(
        "__setitem__",
        (key, TermValue(7)),
        owner="enum._EnumDict.__setitem__",
        blame=site,
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ReceiverOwnedMutationResult)
    transition = outcome.value
    assert transition.receiver_before is receiver
    assert isinstance(transition.receiver_after, GuardedValue)
    assert transition.receiver_after.guard == guard
    assert isinstance(transition.receiver_after.when_true, MappingObjectValue)
    assert isinstance(transition.receiver_after.when_false, MappingObjectValue)
    assert transition.receiver_after.when_true.identity == receiver.identity
    assert transition.receiver_after.when_false.identity == receiver.identity
    return transition.receiver_after


def test_guarded_key_conserves_both_enum_dictionary_post_states() -> None:
    """The key branch changes entries, never receiver identity or cardinality."""
    post = _guarded_transition("_order_", "__order__")

    assert _stored_key(post.when_true) == StringValue("_order_")
    assert _stored_key(post.when_false) == StringValue("__order__")


def test_swapped_key_faces_cannot_choose_or_collapse_one_branch() -> None:
    """Lying arm: swapping the source faces must swap both resulting entries."""
    post = _guarded_transition("__order__", "_order_")

    assert _stored_key(post.when_true) == StringValue("__order__")
    assert _stored_key(post.when_false) == StringValue("_order_")
