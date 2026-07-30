from dataclasses import dataclass

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import (
    MappingObjectValue,
    ObjectValue,
    ReceiverFieldStoreValue,
    ReturnValue,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Complete, Completed
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar, Sugar
from sugar_lift_py_tests.sugar.receiver_field_store_state_sugar import (
    ReceiverFieldStoreStateSugar,
)
from sugar_source_tree.nodes import FunctionDef, ReceiverFieldStoreState, Return
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _StoreReceiverField(Sugar):
    receiver: ObjectValue
    value: TermValue

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return Complete(ReceiverFieldStoreValue(self.receiver, "payload", self.value))


@dataclass(frozen=True)
class _ReadReceiverField(Sugar):
    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return ctx.temporal.value_for("self").attribute("payload", "test")


@dataclass(frozen=True)
class _ReturnAlias(Sugar):
    name: str

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return Complete(ReturnValue(ctx.temporal.value_for(self.name)))


@dataclass(frozen=True)
class _FixedSugar(ConstructedTermSugar):
    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)

    def to_term(self, *, owner: str):
        return self.value.to_term(owner=owner)


def test_receiver_field_store_rebinds_the_same_receiver_for_the_tail():
    """A completed ``self.x = value`` owns the later ``self.x`` projection."""
    receiver = ObjectValue("Renamed", (), identity="receiver-1")
    stored = TermValue(17)
    context = ReduceContext.root(owner="receiver-field-store").with_temporal(
        ReduceContext.root(owner="receiver-field-store-seed")
        .temporal.bind_value("self", receiver)
    )

    exits = reduce_block_to_exitset(
        (_StoreReceiverField(receiver, stored), _ReadReceiverField()), context
    ).exits

    assert len(exits) == 1
    assert isinstance(exits[0], Completed)
    assert exits[0].value.entries[-1] is stored


def test_returned_alias_observes_updated_mapping_receiver_identity():
    receiver = MappingObjectValue(
        "Namespace",
        (),
        identity="receiver-1",
        entries=((StringValue("member"), TermValue(1)),),
    )
    alias = receiver.mapping_with_entries(receiver.entries)
    context = ReduceContext.root(owner="receiver-alias")
    temporal = context.temporal.bind_value("self", receiver)
    temporal = temporal.bind_value("alias", alias)
    context = context.with_temporal(temporal)

    exits = reduce_block_to_exitset(
        (_StoreReceiverField(receiver, TermValue(17)), _ReturnAlias("alias")),
        context,
    ).exits

    assert len(exits) == 1
    returned = next(
        entry
        for entry in exits[0].value.entries
        if isinstance(entry, ReturnValue)
    ).value
    assert isinstance(returned, MappingObjectValue)
    assert returned.identity == receiver.identity
    assert returned.entries == receiver.entries
    assert returned.attribute("payload", "test") == Complete(TermValue(17))


def test_same_class_different_receiver_identity_is_not_rewritten():
    receiver = MappingObjectValue("Namespace", (), identity="receiver-1")
    distinct = MappingObjectValue("Namespace", (), identity="receiver-2")
    context = ReduceContext.root(owner="receiver-alias")
    temporal = context.temporal.bind_value("self", receiver)
    temporal = temporal.bind_value("other", distinct)
    context = context.with_temporal(temporal)

    exits = reduce_block_to_exitset(
        (_StoreReceiverField(receiver, TermValue(17)), _ReturnAlias("other")),
        context,
    ).exits

    returned = next(
        entry
        for entry in exits[0].value.entries
        if isinstance(entry, ReturnValue)
    ).value
    assert returned is distinct
    assert returned.identity == "receiver-2"


def test_shadow_return_of_mutated_alias_reads_post_state() -> None:
    source = (
        "class Namespace:\n"
        "    pass\n\n"
        "def prepare():\n"
        "    namespace = Namespace()\n"
        "    namespace.owner = 7\n"
        "    return namespace\n"
    )
    tree = SourceFile((source, "receiver_return.py", blake3_512_of(source.encode())))
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "prepare"
    )

    substituted = function.substitute({})
    returned = next(node for node in substituted.walk() if isinstance(node, Return))

    assert isinstance(returned.value, ReceiverFieldStoreState)


def test_shadow_store_does_not_rewrite_distinct_alias_return() -> None:
    source = (
        "class Namespace:\n"
        "    pass\n\n"
        "def prepare():\n"
        "    changed = Namespace()\n"
        "    other = Namespace()\n"
        "    changed.owner = 7\n"
        "    return other\n"
    )
    tree = SourceFile((source, "receiver_return.py", blake3_512_of(source.encode())))
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "prepare"
    )

    substituted = function.substitute({})
    returned = next(node for node in substituted.walk() if isinstance(node, Return))

    assert not isinstance(returned.value, ReceiverFieldStoreState)


def test_receiver_field_post_state_preserves_mapping_identity_and_entries() -> None:
    receiver = MappingObjectValue(
        "Namespace",
        (),
        identity="receiver-1",
        entries=((StringValue("member"), TermValue(1)),),
    )

    outcome = ReceiverFieldStoreStateSugar(
        _FixedSugar(receiver),
        _FixedSugar(TermValue(7)),
        "owner",
        "site",
    ).desugar(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, MappingObjectValue)
    assert outcome.value.identity == receiver.identity
    assert outcome.value.entries == receiver.entries
    assert outcome.value.attribute("owner", "test") == Complete(TermValue(7))
