from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import (
    BuiltinSuperValue,
    MappingObjectValue,
    NoneValue,
    ReceiverOwnedMutationResult,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _definition_and_receiver():
    source = (
        "class Mapping(dict):\n"
        "    def __setitem__(self, key, value):\n"
        "        super().__setitem__(key, value)\n"
    )
    tree = SourceFile((source, "mapping_setitem.py", blake3_512_of(source.encode())))
    definition = next(node for node in tree.root.body if isinstance(node, ClassDef))
    value = definition.sugar().desugar(ReduceContext.root(owner="test")).value
    return value, value.construct_receiver_state_from_block(None, "receiver")


def test_builtin_super_setitem_carries_receiver_transition_and_none_separately():
    definition, receiver = _definition_and_receiver()
    outcome = BuiltinSuperValue(definition, receiver).call_method_value(
        "__setitem__",
        (StringValue("member"), TermValue(7)),
        owner="test",
        blame="site",
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ReceiverOwnedMutationResult)
    assert isinstance(
        outcome.value.project_operation_receiver(None, owner="test"), NoneValue
    )
    assert outcome.value.receiver_before is receiver
    assert outcome.value.receiver_after.identity == receiver.identity
    assert outcome.value.receiver_after.entries == (
        (StringValue("member"), TermValue(7)),
    )


def test_receiver_transition_updates_every_exact_identity_alias_only():
    definition, receiver = _definition_and_receiver()
    distinct = MappingObjectValue("Mapping", (), identity="other")
    result = (
        BuiltinSuperValue(definition, receiver)
        .call_method_value(
            "__setitem__",
            (StringValue("member"), TermValue(7)),
            owner="test",
            blame="site",
        )
        .value
    )
    ctx = ReduceContext.root(owner="test")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("left", receiver))
    ctx = ctx.with_temporal(
        ctx.temporal.bind_value("alias", receiver.mapping_with_entries(()))
    )
    ctx = ctx.with_temporal(ctx.temporal.bind_value("distinct", distinct))

    updated = result.extend_scope(ctx)

    assert updated.temporal.value_for("left") == result.receiver_after
    assert updated.temporal.value_for("alias") == result.receiver_after
    assert updated.temporal.value_for("distinct") is distinct


def test_source_setitem_body_projects_updated_receiver_not_none_result():
    _definition, receiver = _definition_and_receiver()

    outcome = receiver.setitem_with_context(
        StringValue("member"),
        TermValue(7),
        "caller",
        ReduceContext.root(owner="caller"),
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, MappingObjectValue)
    assert outcome.value.identity == receiver.identity
    assert outcome.value.entries == ((StringValue("member"), TermValue(7)),)
