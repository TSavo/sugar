from dataclasses import replace

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import (
    BuiltinSuperValue,
    NoneValue,
    ObjectField,
    ObjectValue,
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


def test_builtin_super_setitem_is_the_one_call_never_dicts_answer_here():
    """``super().__setitem__`` over ``Mapping(dict)``: the order after
    ``__class__`` is ``dict``, ``object``.  The lift no longer answers it by
    dict's own mutation (#7757 L5): it is the one dispatched call after
    ``__class__`` (with no workspace root, the unanswered ``super.__setitem__``),
    owed, both faces standing, and no receiver transition is stated."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
    from sugar_lift_py_tests.outcome import Completed

    definition, receiver = _definition_and_receiver()
    outcome = BuiltinSuperValue(definition, receiver).call_method_value(
        "__setitem__",
        (StringValue("member"), TermValue(7)),
        owner="test",
        blame="site",
    )

    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "UnknownCallee:super.__setitem__"
    _binds, call = peel_walrus_binds(done.value)
    assert isinstance(call, CallSiteValue), type(call)
    assert not isinstance(call, ReceiverOwnedMutationResult)
    assert outcome.owed_items()


def test_receiver_transition_updates_every_exact_identity_alias_only():
    definition, receiver = _definition_and_receiver()
    del definition
    distinct = ObjectValue("Mapping", (), identity="other", allocation=FRAME_FRESH)
    # A receiver transition with the operation's ``None`` kept apart: the
    # same object (its identity) after the operation.
    result = ReceiverOwnedMutationResult(
        receiver,
        replace(receiver, fields=(ObjectField("member", TermValue(7)),)),
        NoneValue(),
    )
    ctx = ReduceContext.root(owner="test")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("left", receiver))
    ctx = ctx.with_temporal(
        ctx.temporal.bind_value("alias", replace(receiver))
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
