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
from sugar_lift_py_tests.sugar.store_effect_sugar import AttributeStoreEffectSugar
from sugar_lift_py_tests.sugar.constructed_receiver_ref_sugar import (
    ConstructedReceiverRefSugar,
)
from sugar_lift_py_tests.sugar.expr_statement_sugar import ExprStatementSugar
from sugar_lift_py_tests.sugar.formal_ref_sugar import FormalRefSugar
from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
from sugar_source_tree.nodes import (
    ClassDef,
    FunctionDef,
    ReceiverFieldStoreState,
    Return,
)
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


def test_class_initializer_reaches_the_authenticated_receiver_store_entrance() -> None:
    """The active class initializer must not enter as an arbitrary formal."""
    source = "class Box:\n" "    def __init__(self):\n" "        self.value = 1\n"
    tree = SourceFile((source, "class_receiver.py", blake3_512_of(source.encode())))
    definition = next(
        node
        for node in tree.nodes()
        if isinstance(node, ClassDef) and node.name == "Box"
    )
    initializer = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "__init__"
    )

    universe = initializer.sugar()
    statement = universe.statements[0]
    frame = definition.source_visible_constructor_frame()

    assert isinstance(statement, ExprStatementSugar)
    assert isinstance(statement.value, ReceiverFieldStoreStateSugar)
    assert isinstance(statement.value.receiver, ConstructedReceiverRefSugar)
    assert (
        statement.value.receiver.binding_coordinate_cid
        == frame.body.receiver_coordinate_cid
    )


def test_genuine_formal_receiver_keeps_the_formal_store_entrance() -> None:
    """A module-level formal carries no constructed receiver authority."""
    source = "def mutate(target):\n" "    target.value = 1\n"
    tree = SourceFile((source, "formal_receiver.py", blake3_512_of(source.encode())))
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "mutate"
    )

    universe = function.sugar()
    statement = universe.statements[0]

    assert isinstance(statement, AttributeStoreEffectSugar)
    assert isinstance(statement.receiver, FormalRefSugar)


def test_class_initializer_universe_seats_its_constructed_receiver() -> None:
    """Enumeration binds the exact class receiver before body reduction."""
    source = "class Box:\n" "    def __init__(self):\n" "        self.value = 1\n"
    tree = SourceFile((source, "class_receiver.py", blake3_512_of(source.encode())))
    initializer = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "__init__"
    )

    outcome = function_universe_outcome(initializer)

    assert isinstance(outcome, Complete)


def test_receiver_field_store_rebinds_the_same_receiver_for_the_tail():
    """A completed ``self.x = value`` owns the later ``self.x`` projection."""
    receiver = ObjectValue("Renamed", (), identity="receiver-1")
    stored = TermValue(17)
    context = ReduceContext.root(owner="receiver-field-store").with_temporal(
        ReduceContext.root(owner="receiver-field-store-seed").temporal.bind_value(
            "self", receiver
        )
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
        entry for entry in exits[0].value.entries if isinstance(entry, ReturnValue)
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
        entry for entry in exits[0].value.entries if isinstance(entry, ReturnValue)
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


def test_receiver_field_post_state_preserves_defining_class_authority() -> None:
    defining_class = object()
    receiver = ObjectValue(
        "Namespace", (), identity="receiver-1", defining_class=defining_class
    )

    outcome = ReceiverFieldStoreStateSugar(
        _FixedSugar(receiver), _FixedSugar(TermValue(7)), "owner", "site"
    ).desugar(None)

    assert isinstance(outcome, Complete)
    assert outcome.value.defining_class is defining_class


def test_receiver_field_post_state_does_not_borrow_foreign_class_authority() -> None:
    own_class = object()
    foreign_class = object()
    receiver = ObjectValue(
        "Namespace", (), identity="receiver-1", defining_class=own_class
    )
    foreign = ObjectValue(
        "Namespace", (), identity="receiver-1", defining_class=foreign_class
    )

    updated = receiver.with_field_store("owner", TermValue(7))

    assert updated.defining_class is own_class
    assert updated.defining_class is not foreign.defining_class
