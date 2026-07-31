"""The shadow AST threads the post-state of ``dict.setdefault`` chains."""

from dataclasses import dataclass, field

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ListValue,
    MappingObjectValue,
    ObjectField,
    ReceiverOwnedMutationResult,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.dict_setdefault_append_state_sugar import (
    DictSetDefaultAppendStateSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_source_tree.nodes import (
    Call,
    DictSetDefaultAppendState,
    DictSetDefaultAppendStatement,
    FunctionDef,
)
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _FloorSugar(ConstructedTermSugar):
    value: object
    evaluations: list[str] = field(compare=False)
    label: str
    site: object = field(default="test", compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        self.evaluations.append(self.label)
        return Complete(self.value)

    def to_term(self, *, owner):
        return self.value.to_term(owner=owner)


def _project_return(source: str):
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, "dict_setdefault_fixture.py", blake3_512_of(source.encode())),
        construction_context=context,
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    substituted = function.substitute({})
    assert any(
        isinstance(node, DictSetDefaultAppendStatement) for node in substituted.walk()
    )
    assert any(
        isinstance(node, DictSetDefaultAppendState) for node in substituted.walk()
    )
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    span = call.line_col_span()
    coordinate = SourceFragmentCoordinateV1(
        call.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    context.source_call_frames[coordinate] = function.source_visible_call_frame()
    outcome = call.sugar().desugar(None)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    projected = outcome.value.project_operation_receiver_outcome(
        None, owner="test_dict_setdefault_shadow_state"
    )
    assert isinstance(projected, Complete)
    return projected.value


def test_missing_key_insert_and_append_are_visible_to_later_read() -> None:
    projected = _project_return(
        "def producer():\n"
        "    d = {}\n"
        "    d.setdefault('_ignore_', []).append('_ignore_')\n"
        "    return d['_ignore_']\n\n"
        "producer()\n"
    )
    assert projected == ListValue((StringValue("_ignore_"),))


def test_existing_key_wins_over_default_before_append() -> None:
    projected = _project_return(
        "def producer():\n"
        "    d = {'x': [1]}\n"
        "    d.setdefault('x', [9]).append(2)\n"
        "    return d['x']\n\n"
        "producer()\n"
    )
    assert projected == ListValue((TermValue(1), TermValue(2)))
    assert projected != ListValue((TermValue(9), TermValue(2)))


def test_authenticated_dict_subclass_keeps_receiver_identity_and_fields() -> None:
    order: list[str] = []
    receiver = MappingObjectValue(
        "DerivedDict",
        (ObjectField("source_field", TermValue(7)),),
        identity="receiver-coordinate",
    )
    sugar = DictSetDefaultAppendStateSugar(
        receiver=_FloorSugar(receiver, order, "receiver"),
        key=_FloorSugar(StringValue("members"), order, "key"),
        default=_FloorSugar(ListValue(()), order, "default"),
        appended=_FloorSugar(StringValue("member"), order, "appended"),
        site="mutation-site",
    )

    outcome = sugar.desugar(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ReceiverOwnedMutationResult)
    updated = outcome.value.receiver_after
    assert isinstance(updated, MappingObjectValue)
    assert updated.identity == "receiver-coordinate"
    assert updated.fields == receiver.fields
    assert updated.entries == (
        (StringValue("members"), ListValue((StringValue("member"),))),
    )
    assert order == ["receiver", "key", "default", "appended"]


def test_authenticated_dict_subclass_setdefault_uses_existing_value() -> None:
    order: list[str] = []
    receiver = MappingObjectValue(
        "DerivedDict",
        (),
        identity="receiver-coordinate",
        entries=((StringValue("members"), ListValue((TermValue(1),))),),
    )
    sugar = DictSetDefaultAppendStateSugar(
        receiver=_FloorSugar(receiver, order, "receiver"),
        key=_FloorSugar(StringValue("members"), order, "key"),
        default=_FloorSugar(ListValue((TermValue(99),)), order, "default"),
        appended=_FloorSugar(TermValue(2), order, "appended"),
        site="mutation-site",
    )

    outcome = sugar.desugar(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ReceiverOwnedMutationResult)
    updated = outcome.value.receiver_after
    assert isinstance(updated, MappingObjectValue)
    assert updated.entries == (
        (StringValue("members"), ListValue((TermValue(1), TermValue(2)))),
    )
    assert order == ["receiver", "key", "default", "appended"]


def test_setdefault_append_does_not_invent_source_setitem_redispatch() -> None:
    class _OverrideTrap(MappingObjectValue):
        def setitem_with_context(self, index, value, site, ctx):
            raise AssertionError("inherited dict.setdefault must not call __setitem__")

    receiver = _OverrideTrap("DerivedDict", (), identity="receiver-coordinate")
    sugar = DictSetDefaultAppendStateSugar(
        receiver=_FloorSugar(receiver, [], "receiver"),
        key=_FloorSugar(StringValue("members"), [], "key"),
        default=_FloorSugar(ListValue(()), [], "default"),
        appended=_FloorSugar(StringValue("member"), [], "appended"),
        site="mutation-site",
    )

    outcome = sugar.desugar(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ReceiverOwnedMutationResult)
    assert outcome.value.receiver_after.entries == (
        (StringValue("members"), ListValue((StringValue("member"),))),
    )


def test_mutation_result_and_shadow_post_state_are_distinct_projections() -> None:
    from sugar_lift_py_tests.floor import NoneValue

    receiver = MappingObjectValue("DerivedDict", (), identity="receiver-coordinate")
    updated = receiver.mapping_with_entries(
        ((StringValue("members"), ListValue((StringValue("member"),))),)
    )
    mutation = ReceiverOwnedMutationResult(receiver, updated, NoneValue())

    result = mutation.answer(None)
    post_state = mutation.project_receiver_post_state(
        None, owner="test", blame="mutation-site"
    )

    assert isinstance(result, Complete)
    assert isinstance(result.value, NoneValue)
    assert isinstance(post_state, Complete)
    assert post_state.value is updated


def test_mapping_mutation_advances_only_aliases_with_the_same_identity() -> None:
    from sugar_lift_py_tests.context import ReduceContext

    receiver = MappingObjectValue(
        "DerivedDict", (), identity="receiver-coordinate"
    )
    foreign = MappingObjectValue("DerivedDict", (), identity="foreign-coordinate")
    sugar = DictSetDefaultAppendStateSugar(
        receiver=_FloorSugar(receiver, [], "receiver"),
        key=_FloorSugar(StringValue("members"), [], "key"),
        default=_FloorSugar(ListValue(()), [], "default"),
        appended=_FloorSugar(StringValue("member"), [], "appended"),
        site="mutation-site",
    )
    outcome = sugar.desugar(None)
    assert isinstance(outcome, Complete)
    mutation = outcome.value
    assert isinstance(mutation, ReceiverOwnedMutationResult)

    ctx = ReduceContext.root(owner="test")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("classdict", receiver))
    ctx = ctx.with_temporal(ctx.temporal.bind_value("foreign", foreign))
    advanced = mutation.extend_scope(ctx)

    assert advanced.temporal.value_for("classdict") is mutation.receiver_after
    assert advanced.temporal.value_for("foreign") is foreign


def test_guarded_mapping_mutation_preserves_identity_and_only_conditions_post_state() -> None:
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor import GuardedValue
    from sugar_lift_py_tests.ir import atomic

    receiver = MappingObjectValue("DerivedDict", (), identity="receiver-coordinate")
    foreign = MappingObjectValue("DerivedDict", (), identity="foreign-coordinate")
    updated = receiver.mapping_with_entries(
        ((StringValue("members"), ListValue((StringValue("member"),))),)
    )
    mutation = ReceiverOwnedMutationResult(receiver, updated, TermValue(None))
    guard = atomic("test:mutation-selected", [])

    guarded = mutation.guarded(guard)
    ctx = ReduceContext.root(owner="test")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("classdict", receiver))
    ctx = ctx.with_temporal(ctx.temporal.bind_value("foreign", foreign))
    advanced = guarded.extend_scope(ctx)

    classdict = advanced.temporal.value_for("classdict")
    assert isinstance(classdict, GuardedValue)
    assert classdict.guard == guard
    assert classdict.when_true is updated
    assert classdict.when_false is receiver
    assert advanced.temporal.value_for("foreign") is foreign
    assert guarded.receiver_before is receiver
    assert guarded.result == mutation.result
