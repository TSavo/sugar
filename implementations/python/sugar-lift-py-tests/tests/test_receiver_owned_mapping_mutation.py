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
        .completed_value()
    )
    assert isinstance(result, ReceiverOwnedMutationResult)
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
    """``receiver["member"] = 7`` through the source ``__setitem__``.

    Expected value changed (#7757 steps 5 and 6, #8738, #8751): the store
    no longer applies the method's body, so the receiver is not read as the
    mapping it left (``entries == (("member", 7),)``).  The implicit call is
    the method's coordinate and edge: on its completed face the receiver
    after the call is unknown (``python:receiver_after_call``), never the
    ``None`` the method returns, and the call owes its halt under the
    complement.  What the method does to the receiver is joined at prove
    (#7757 step 7)."""
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.outcome import Completed, Halted

    _definition, receiver = _definition_and_receiver()

    outcome = receiver.setitem(
        StringValue("member"),
        TermValue(7),
        "caller",
        ReduceContext.root(owner="caller"),
    )

    assert [face for face in outcome.exits if isinstance(face, Halted)], outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds

    _writes, after = peel_walrus_binds(completed[0].value)
    assert not isinstance(after, NoneValue)
    assert isinstance(after, SymbolicValue), after
    assert after.term.name == "python:receiver_after_call"
