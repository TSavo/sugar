"""Conservation laws for the receiver-field shadow mutation transition."""

from dataclasses import dataclass

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import (
    NoneValue,
    ObjectValue,
    ReceiverOwnedMutationResult,
    TermValue,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_body
from sugar_lift_py_tests.sugar.receiver_field_store_state_sugar import (
    ReceiverFieldStoreStateSugar,
)
from sugar_lift_py_tests.sugar.receiver_mutation_post_state_sugar import (
    ReceiverMutationPostStateSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_source_tree.nodes import (
    FunctionDef,
    ReceiverFieldStoreState,
    ReceiverFieldStoreStatement,
    ReceiverMutationPostState,
    Return,
)
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _FixedSugar(ConstructedTermSugar):
    value: object
    evaluations: list[str]
    label: str

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        self.evaluations.append(self.label)
        return Complete(self.value)

    def to_term(self, *, owner: str):
        return self.value.to_term(owner=owner)


def _mutation(*, identity="receiver-1", evaluations=None):
    evaluations = [] if evaluations is None else evaluations
    receiver = ObjectValue("Namespace", (), identity=identity)
    sugar = ReceiverFieldStoreStateSugar(
        _FixedSugar(receiver, evaluations, "receiver"),
        _FixedSugar(TermValue(7), evaluations, "value"),
        "owner",
        "source.py:3:4",
    )
    return receiver, sugar, evaluations


def test_statement_value_publishes_one_receiver_owned_mutation_result():
    receiver, sugar, evaluations = _mutation()

    outcome = sugar.desugar(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ReceiverOwnedMutationResult)
    assert outcome.value.receiver_before is receiver
    assert isinstance(outcome.value.result, NoneValue)
    assert evaluations == ["receiver", "value"]


def test_later_alias_projection_reads_receiver_after_not_assignment_none():
    receiver, mutation, evaluations = _mutation()
    projection = ReceiverMutationPostStateSugar(mutation, "source.py:3:4")

    outcome = projection.desugar(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ObjectValue)
    assert outcome.value.identity == receiver.identity
    assert outcome.value.attribute("owner", "read") == Complete(TermValue(7))
    assert not isinstance(outcome.value, NoneValue)
    assert evaluations == ["receiver", "value"]


def test_receiver_mutation_leaves_a_distinct_identity_unchanged():
    receiver, sugar, _ = _mutation()
    distinct = ObjectValue("Namespace", (), identity="receiver-2")
    outcome = sugar.desugar(None)
    mutation = outcome.value
    ctx = ReduceContext.root(owner="audit")
    temporal = ctx.temporal.bind_value("self", receiver)
    temporal = temporal.bind_value("other", distinct)

    advanced = mutation.extend_scope(ctx.with_temporal(temporal))

    assert advanced.temporal.value_for("self") is mutation.receiver_after
    assert advanced.temporal.value_for("other") is distinct


def test_reduce_body_carries_mutation_into_final_context():
    receiver, sugar, _ = _mutation()
    ctx = ReduceContext.root(owner="audit")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("self", receiver))

    outcome = reduce_body((sugar,), ctx)

    assert isinstance(outcome, Complete)
    final_context = outcome.value.final_context
    assert final_context is not None
    advanced = final_context.temporal.value_for("self")
    assert advanced.identity == receiver.identity
    assert advanced.attribute("owner", "read") == Complete(TermValue(7))


def test_post_state_projection_consumes_one_store_without_reconstructing_it(monkeypatch):
    _receiver, mutation, evaluations = _mutation()
    calls = 0
    original = ReceiverFieldStoreStateSugar.desugar

    def counted(self, ctx=None):
        nonlocal calls
        calls += 1
        return original(self, ctx)

    monkeypatch.setattr(ReceiverFieldStoreStateSugar, "desugar", counted)

    outcome = ReceiverMutationPostStateSugar(
        mutation, "source.py:3:4"
    ).desugar(None)

    assert isinstance(outcome, Complete)
    assert calls == 1
    assert evaluations == ["receiver", "value"]


def test_shadow_projection_retains_the_one_store_coordinate():
    source = (
        "class Namespace:\n"
        "    pass\n\n"
        "def prepare():\n"
        "    namespace = Namespace()\n"
        "    namespace.owner = 7\n"
        "    return namespace\n"
    )
    tree = SourceFile((source, "receiver_store.py", blake3_512_of(source.encode())))
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "prepare"
    )

    substituted = function.substitute({})
    statement = next(
        node for node in substituted.walk() if isinstance(node, ReceiverFieldStoreStatement)
    )
    returned = next(node for node in substituted.walk() if isinstance(node, Return))

    assert isinstance(statement.post_state, ReceiverFieldStoreState)
    assert isinstance(returned.value, ReceiverMutationPostState)
    assert isinstance(returned.value.mutation, ReceiverFieldStoreState)
    assert returned.value.mutation.fragment.seal().cid == statement.post_state.fragment.seal().cid
    assert returned.value.mutation.sugar().to_term(
        owner="audit"
    ) == statement.post_state.sugar().to_term(owner="audit")
