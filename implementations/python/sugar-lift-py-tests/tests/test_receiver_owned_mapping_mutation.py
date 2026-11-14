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
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

from frame_fresh import FRAME_FRESH


def _definition_and_receiver():
    source = (
        "class Mapping(dict):\n"
        "    def __setitem__(self, key, value):\n"
        "        super().__setitem__(key, value)\n"
    )
    tree = SourceFile(
        (source, "mapping_setitem.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    definition = next(node for node in tree.root.body if isinstance(node, ClassDef))
    outcome = definition.sugar().desugar(ReduceContext.root(owner="test"))
    value = outcome.completed_value()
    return value, value.fresh_receiver("receiver", allocation=FRAME_FRESH)


def test_builtin_super_setitem_carries_receiver_transition_and_none_separately():
    definition, receiver = _definition_and_receiver()
    outcome = BuiltinSuperValue(definition, receiver).call_method_value(
        "__setitem__",
        (StringValue("member"), TermValue(7)),
        owner="test",
        blame="site",
    )

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), ReceiverOwnedMutationResult)
    assert isinstance(
        outcome.completed_value().project_operation_receiver(None, owner="test"), NoneValue
    )
    assert outcome.completed_value().receiver_before is receiver
    assert outcome.completed_value().receiver_after.identity == receiver.identity
    assert outcome.completed_value().receiver_after.entries == (
        (StringValue("member"), TermValue(7)),
    )


def test_receiver_transition_updates_every_exact_identity_alias_only():
    definition, receiver = _definition_and_receiver()
    distinct = MappingObjectValue(
        "Mapping", (), identity="other", allocation=FRAME_FRESH
    )
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

    outcome = receiver.setitem(
        StringValue("member"),
        TermValue(7),
        "caller",
        ReduceContext.root(owner="caller"),
    )

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), MappingObjectValue)
    assert outcome.completed_value().identity == receiver.identity
    assert outcome.completed_value().entries == ((StringValue("member"), TermValue(7)),)
