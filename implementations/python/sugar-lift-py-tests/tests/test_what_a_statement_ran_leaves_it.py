"""What a statement ran before or inside it is what follows it reads, and
what its record carries (#7757, leftovers of #8147).

- A ``with`` publishes its body's post-states (``With._published``): the
  statement after it reads a name the body rebound, or a container the body
  mutated, as the body left it -- never as it stood before the ``with``.
- An assignment lays the callee stores its values carried in its record
  whatever its last step makes -- a class body's fields too -- and in the
  record of a halt after a value was computed (a later value's, a store
  target's) (``function_universe_sugar.laid_in_record``).
- A statement's header (an ``if`` or ``assert`` test, a live ``while``'s test
  at each item, a ``with`` item's manager, a ``match`` subject, a ``raise``
  operand) reaches the rest of the statement by the one header rule
  (``function_universe_sugar.header_applied``): its walrus binds and callee
  stores are in the context the rest runs in -- and what follows the
  statement reads -- and the stores in every record it makes.
- A class statement lays its body's callee stores once in its record and
  publishes them to its block (``ClassDefinitionSugar.as_statement``); the
  class value holds none of them, so a read of it applies nothing.  A
  decorated class statement lays them the same way, before what its
  decorators stored (``DecoratorApplicationSugar.runs_statement``); and a
  class statement run more than once (each item of a loop) lays them at
  each run.
- No evaluation is answered from a record of an earlier one: every read of
  a value a statement evaluated is a reference to the statement's
  evaluation key, given at construction (``EvaluationRefSugar``).  The
  ordinary call a mutating method takes reads its receiver through the key
  the one door binds it under (``PathContainerCall.receiver_evaluation``).
- A ``for`` the unroll dissolves evaluates its iterable's calls before the
  first item (``For._evaluated_before_the_first_item``), whatever the item's
  shape: an earlier item's ``break`` never drops a later item's call, and a
  later item's unpack still runs where that item is taken, reading the
  element under the item's evaluation key -- no name is made up for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.container_mutation import _identity
from sugar_source_tree.nodes import Assign, Call, Expr, FunctionDef, Name, Return
from sugar_source_tree.tree import SourceFile


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "statement_leaves.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _returned(rewritten):
    (statement,) = [node for node in rewritten.body if isinstance(node, Return)]
    return _identity(statement.value)


# ---------------------------------------------------------------------------
# (1) A with publishes its body's post-states.
# ---------------------------------------------------------------------------


def test_a_container_the_with_body_mutated_is_read_after_the_with_as_it_left_it():
    rewritten = _function(
        "def f(m):\n"
        "    acc = []\n"
        "    with m:\n"
        "        acc.append(1)\n"
        "    return acc\n"
    ).substitute({})
    # The object after the body's append, never the ``[]`` before the with.
    assert _returned(rewritten).kind != "List"


def test_a_name_the_with_body_rebound_is_read_after_the_with_as_it_left_it():
    rewritten = _function(
        "def f(m):\n"
        "    x = 0\n"
        "    with m:\n"
        "        x = 1\n"
        "    return x\n"
    ).substitute({})
    returned = _returned(rewritten)
    assert returned.kind == "Constant"
    assert returned.value == 1


# ---------------------------------------------------------------------------
# (2) An assignment lays its callee stores in every record it makes.
# ---------------------------------------------------------------------------


def _caller_holding_a_receiver():
    """A caller context binding ``box`` to an object, and the field store a
    callee made on that object."""
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor import (
        ObjectValue,
        ReceiverFieldStoreValue,
        TermValue,
    )

    from frame_fresh import FRAME_FRESH

    receiver = ObjectValue("Box", (), identity="box-1", allocation=FRAME_FRESH)
    ctx = ReduceContext.root(owner="statement-leaves").with_temporal(
        ReduceContext.root(owner="statement-leaves-seed").temporal.bind_value(
            "box", receiver
        )
    )
    store = ReceiverFieldStoreValue(receiver, "x", TermValue(1))
    return ctx, store, receiver.with_field_store("x", TermValue(1))


class _Answers:
    """A right-hand side (or header) whose outcome is ``outcome``."""

    site = None

    def __init__(self, outcome):
        self.outcome = outcome

    def desugar(self, ctx=None):
        return self.outcome


def _carrying(store):
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.named_expression_value import (
        carry_caller_stores,
    )
    from sugar_lift_py_tests.outcome import ExitSet

    return _Answers(ExitSet.completed(carry_caller_stores((store,), TermValue(2))))


def _raised():
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    return RaiseEffect.for_builtin("ValueError", blame="statement_leaves.py:3:4")


def test_an_assignment_tail_lays_its_callee_store_in_the_block_record() -> None:
    """``y = g(box)`` where ``g`` stored ``box.x``, its tail completing with
    a block's record (a class body's record is its block's): the record
    carries the store, which the class statement lays before the class."""
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.assigned_value import evaluate_assignment_values
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    ctx, store, _stored = _caller_holding_a_receiver()
    outcome = evaluate_assignment_values(
        (_carrying(store),),
        ctx,
        tail=lambda active, completed: ExitSet.completed(
            _ReducedBlock((), True, ())
        ),
    )
    body = outcome.completed_value()
    assert isinstance(body, _ReducedBlock)
    assert body.entries == (store,)


def test_a_store_target_halting_after_the_value_keeps_its_callee_store() -> None:
    """``o.y = g(box)`` whose store halts after ``g`` stored ``box.x``: the
    halt's record carries the store, in the context the value left."""
    from sugar_lift_py_tests.outcome import ExitSet, Halted
    from sugar_lift_py_tests.sugar.assigned_value import evaluate_assignment_values

    ctx, store, stored = _caller_holding_a_receiver()
    outcome = evaluate_assignment_values(
        (_carrying(store),),
        ctx,
        tail=lambda active, completed: ExitSet.halted(_raised()),
    )
    (halt,) = outcome.exits
    assert isinstance(halt, Halted)
    assert halt.state.entries == (store,)
    assert halt.state.context.temporal.value_for("box") == stored


def test_a_later_value_halting_keeps_an_earlier_values_callee_store() -> None:
    """``a, b = g(box), h()`` where ``g`` stored ``box.x`` and ``h`` raised:
    the halt's record carries the store, never the block's prefix alone."""
    from sugar_lift_py_tests.outcome import ExitSet, Halted
    from sugar_lift_py_tests.sugar.assigned_value import evaluate_assignment_values

    ctx, store, stored = _caller_holding_a_receiver()
    outcome = evaluate_assignment_values(
        (_carrying(store), _Answers(ExitSet.halted(_raised()))), ctx
    )
    (halt,) = outcome.exits
    assert isinstance(halt, Halted)
    assert halt.state.entries == (store,)
    assert halt.state.context.temporal.value_for("box") == stored


# ---------------------------------------------------------------------------
# (3) A header's writes reach the rest of its statement by one rule.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Headed:
    """A statement with a header: the rest completes with an empty record in
    the context it ran in, or halts with no record of its own."""

    header: object
    halts: bool = False
    site: object = None

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            header_applied,
        )

        headed, outcome = header_applied(self, "header", ctx)
        if headed is not None:
            return headed
        if self.halts:
            return outcome.and_then(lambda _value: ExitSet.halted(_raised()))
        return outcome.and_then(
            lambda _value: ExitSet.completed(_ReducedBlock((), True, (), context=ctx))
        )


def test_a_headers_callee_store_reaches_the_rest_and_its_record() -> None:
    ctx, store, stored = _caller_holding_a_receiver()
    record = _Headed(_carrying(store)).desugar(ctx).completed_value()
    assert record.entries == (store,)
    assert record.context.temporal.value_for("box") == stored


def test_a_halt_after_the_header_keeps_its_callee_store() -> None:
    from sugar_lift_py_tests.outcome import Halted

    ctx, store, stored = _caller_holding_a_receiver()
    (halt,) = _Headed(_carrying(store), halts=True).desugar(ctx).exits
    assert isinstance(halt, Halted)
    assert halt.state.entries == (store,)
    assert halt.state.context.temporal.value_for("box") == stored


def _presenting(store, value):
    """A header whose value presents ``value``, carrying the callee
    ``store``."""
    from sugar_lift_py_tests.floor.named_expression_value import (
        carry_caller_stores,
    )
    from sugar_lift_py_tests.outcome import ExitSet

    return _Answers(ExitSet.completed(carry_caller_stores((store,), value)))


def test_an_asserts_test_callee_store_reaches_what_follows_and_its_record() -> None:
    """``assert g(box)`` where ``g`` stored ``box.x``: the test is the
    assert's header (``header_applied``): the statement after the assert
    reads ``box`` as ``g`` left it, and the assert's record carries the
    store before the fact it states."""
    from sugar_lift_py_tests.sugar.assert_sugar import AssertSugar
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    ctx, store, stored = _caller_holding_a_receiver()
    statement = AssertSugar(
        test=_presenting(store, TrueBoolLiteralSugar(site=None)), site=None
    )
    record = reduce_block_to_exitset((statement,), ctx).completed_value()
    assert record.entries[0] == store
    assert record.context.temporal.value_for("box") == stored


def test_a_while_tests_callee_store_is_laid_in_its_items_record() -> None:
    """``while g(box): ...``: the test runs before every item, so each
    evaluation is that item's header: the store is in the context the item's
    body runs in and in the item's record (``_WhileTest.entries``), which the
    loop lays after the items before it (``_after_test``)."""
    from sugar_lift_py_tests.outcome.exit_set import _is_true
    from sugar_lift_py_tests.sugar.function_universe_sugar import header_applied
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
        _WhileItemTestV1,
        _WhileTest,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    ctx, store, stored = _caller_holding_a_receiver()
    headed, _test = header_applied(
        _WhileItemTestV1(_presenting(store, TrueBoolLiteralSugar(site=None))),
        "test",
        ctx,
    )
    assert headed is not None
    item = headed.completed_value()
    assert isinstance(item, _WhileTest)
    assert _is_true(item.formula)
    assert item.entries == (store,)
    assert item.ctx.temporal.value_for("box") == stored


def test_a_symbolic_ifs_test_callee_store_reaches_what_follows_the_if() -> None:
    """``if g(box): ...`` on a test no constant decides: the context after
    the ``if`` reads ``box`` as ``g`` left it -- never as it stood before the
    test -- and the ``if``'s record carries the store first."""
    from sugar_lift_py_tests.floor.branch_result_coordinate import (
        BranchResultCoordinate,
    )
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )
    from sugar_lift_py_tests.sugar.if_sugar import IfSugar
    from sugar_source_tree.binding_state import BranchResultSlot

    ctx, store, stored = _caller_holding_a_receiver()
    statement = IfSugar(
        test=_presenting(
            store, BranchResultCoordinate(BranchResultSlot(slot_id="tested"))
        ),
        branch_slot=BranchResultSlot(slot_id="if"),
        then_body=(),
        else_body=(),
        site=None,
    )
    record = reduce_block_to_exitset((statement,), ctx).completed_value()
    assert record.entries[0] == store
    assert record.context.temporal.value_for("box") == stored


@dataclass(frozen=True)
class _Tally:
    """A store a callee made on an object the caller sees: each time a
    context applies it, its ``tally`` counts one more."""

    def extend_scope(self, ctx):
        from sugar_lift_py_tests.floor import TermValue

        held = ctx.temporal.value_if_bound("tally")
        count = 0 if held is None else held.value
        tallied = ctx.temporal.bind_value("tally", TermValue(count + 1))
        return ctx.with_temporal(tallied)


def _class_statement(store, site=None):
    """``class C: x = f(acc)`` where ``f`` made ``store``: the class
    statement's sugar, its one field's value carrying the store, at
    ``site``."""
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.floor import ConstructedClassFieldV1
    from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar
    from sugar_lift_py_tests.sugar.class_definition_sugar import ClassDefinitionSugar
    from sugar_lift_py_tests.temporal.temporal_context import (
        EVALUATION_PREFIX,
        projection_key,
    )

    occurrence = SourceFragmentCoordinateV1("statement_leaves.py", 2, 4, 2, 5)
    value = _carrying(store)
    key = projection_key(EVALUATION_PREFIX + "field-x", "x")
    return ClassDefinitionSugar(
        class_name="C",
        source_identity_cid="statement_leaves.py",
        definition_fragment_cid="class-c",
        methods=(),
        fields=(
            ConstructedClassFieldV1(
                "x",
                "field-x",
                value,
                SourceFragmentCoordinateV1("statement_leaves.py", 3, 4, 3, 5),
                evaluation_key=key,
            ),
        ),
        # The body is a block: its one statement binds ``x`` under its key.
        body=(AssignSugar(name="x", value=value, site=site, evaluations=(("x", key),)),),
        docstring_cid=None,
        annotation_cids=(),
        decorator_cids=(),
        binding_target_occurrence=occurrence,
        base_sugars=(),
        base_fragment_cids=(),
        site=site,
    )


def test_a_class_statement_lays_its_body_store_once_and_c_alone_applies_none():
    """``class C: x = f(acc)``, then ``C`` on its own line, then a read of
    ``acc``: the body ran once, at the class statement, so the read sees one
    store, not two.  The class statement's record lays the store and
    publishes it to the block (``ClassDefinitionSugar.as_statement``); the
    class value holds none of it, so evaluating ``C`` applies nothing."""
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.class_definition_value import (
        ClassDefinitionValue,
    )
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.sugar.expr_statement_sugar import ExprStatementSugar
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )

    store = _Tally()
    statement = _class_statement(store)
    ctx = ReduceContext.root(owner="statement-leaves")
    record = reduce_block_to_exitset(
        (statement, ExprStatementSugar(value=statement, site=None)), ctx
    ).completed_value()
    assert record.context.temporal.value_if_bound("tally") == TermValue(1)
    assert record.entries.count(store) == 1
    classes = [
        entry for entry in record.entries if isinstance(entry, ClassDefinitionValue)
    ]
    assert len(classes) == 2
    assert all(not hasattr(cls, "body_stores") for cls in classes)


def test_a_read_of_the_class_value_carries_no_body_store() -> None:
    """Every read of the class (``C`` alone, a call of it) presents the
    class beneath its body's stores: only the statement's run carries them
    (``ClassDefinitionSugar.statement_run``)."""
    from sugar_lift_py_tests.floor.class_definition_value import (
        ClassDefinitionValue,
    )
    from sugar_lift_py_tests.floor.named_expression_value import (
        caller_stores_of,
        peel_walrus_binds,
    )
    from sugar_lift_py_tests.context import ReduceContext

    store = _Tally()
    statement = _class_statement(store)
    ctx = ReduceContext.root(owner="statement-leaves")
    read = statement.desugar(ctx).completed_value()
    assert isinstance(read, ClassDefinitionValue)
    run = statement.statement_run().desugar(ctx).completed_value()
    binds, ran = peel_walrus_binds(run)
    assert caller_stores_of(binds)[1] == (store,)
    assert ran == read


def _decorated(statement, *, runs_statement, evaluation=None):
    """``@d class C: ...`` over ``statement``, ``d`` returning its argument:
    the statement's own application (``runs_statement``), or a read of the
    name through the statement's key ``evaluation``."""
    from sugar_lift_py_tests.sugar.decorator_application_sugar import (
        DecoratorApplicationSugar,
        DecoratorStepV1,
    )

    return DecoratorApplicationSugar(
        definition_name="C",
        decorators=(DecoratorStepV1.identity(None, "d"),),
        definition_frame=None,
        definition_class=statement,
        refusal=None,
        site=statement.site,
        evaluation=evaluation,
        runs_statement=runs_statement,
    )


def test_a_decorated_class_statement_lays_its_body_store_once() -> None:
    """``@d class C: x = f(acc)`` where substitution bound no key: the class
    body runs once, at the statement, before ``d`` applies, and the
    statement lays the store in its record exactly as the undecorated one
    does (``DecoratorApplicationSugar.as_statement``) -- never dropped
    because ``d`` received the class value."""
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )

    store = _Tally()
    statement = _decorated(_class_statement(store), runs_statement=True)
    ctx = ReduceContext.root(owner="statement-leaves")
    record = reduce_block_to_exitset((statement,), ctx).completed_value()
    assert record.context.temporal.value_if_bound("tally") == TermValue(1)
    assert record.entries.count(store) == 1


def test_a_decorated_class_statement_binding_its_key_lays_its_body_store_once():
    """``@d class C: x = f(acc)`` bound under its evaluation key: the
    statement is the assignment of the decorators' result
    (``nodes._decorated_statement_sugar``), which lays the body's store the
    application carried in its record, once."""
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )

    store = _Tally()
    application = _decorated(_class_statement(store), runs_statement=True)
    statement = AssignSugar(name="C", value=application, site=None)
    ctx = ReduceContext.root(owner="statement-leaves")
    record = reduce_block_to_exitset((statement,), ctx).completed_value()
    assert record.context.temporal.value_if_bound("tally") == TermValue(1)
    assert record.entries.count(store) == 1


def test_a_read_of_a_decorated_class_never_runs_the_class_statement() -> None:
    """A read of the decorated name is the value the statement bound under
    its key: it runs no class body and applies no decorator.  Where nothing
    bound the key the read is refused by name; the class statement is never
    reduced in its place (#7757 item 21)."""
    import pytest

    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX

    key = EVALUATION_PREFIX + "blake3-512:class-statement/C"
    store = _Tally()
    read = _decorated(_class_statement(store), runs_statement=False, evaluation=key)
    ctx = ReduceContext.root(owner="statement-leaves")
    value = TermValue(7)
    bound = ScopeRebind(key, value).extend_scope(ctx)
    assert read.desugar(bound).completed_value() is value
    with pytest.raises(ConstructionPanic, match="unbound"):
        read.desugar(ctx)


def _class_in_a_loop_site():
    """The ``class C`` statement's fragment in ``for i in (1, 2): class C:
    x = f(acc)``."""
    from sugar_source_tree.nodes import ClassDef

    function = _function(
        "def g(acc):\n"
        "    for i in (1, 2):\n"
        "        class C:\n"
        "            x = f(acc)\n"
    )
    return next(node for node in function.walk() if isinstance(node, ClassDef)).fragment


# A live loop's target, whose items the tests below enter
# (``occurrence.loop_iteration_segment``).
_LOOP_TARGET = "blake3:statement-leaves-loop-target"


def _run_at_each_item(statement, store, ctx):
    """``statement`` run as a block at each item of ``for i in (1, 2):``:
    the context after the loop, and how many times each item's record lays
    ``store``."""
    from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )

    counts = []
    for index in (0, 1):
        with entered(loop_iteration_segment(_LOOP_TARGET, index)):
            record = reduce_block_to_exitset((statement,), ctx).completed_value()
            counts.append(record.entries.count(store))
            ctx = record.context
    return ctx, counts


def test_a_class_statement_run_twice_applies_its_body_store_twice() -> None:
    """``for i in (1, 2): class C: x = f(acc)``: each item runs the class
    statement, so ``f``'s store is applied once per item -- twice."""
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.context import ReduceContext

    store = _Tally()
    statement = _class_statement(store, site=_class_in_a_loop_site())
    ctx, counts = _run_at_each_item(
        statement, store, ReduceContext.root(owner="statement-leaves")
    )
    assert ctx.temporal.value_if_bound("tally") == TermValue(2)
    assert counts == [1, 1]


def test_a_decorated_class_statement_run_twice_applies_its_body_store_twice():
    """``for i in (1, 2): @d class C: x = f(acc)``: the statement's own
    application runs the body at each item."""
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.context import ReduceContext

    store = _Tally()
    definition = _class_statement(store, site=_class_in_a_loop_site())
    ctx, counts = _run_at_each_item(
        _decorated(definition, runs_statement=True),
        store,
        ReduceContext.root(owner="statement-leaves"),
    )
    assert ctx.temporal.value_if_bound("tally") == TermValue(2)
    assert counts == [1, 1]


@dataclass(frozen=True)
class _StoringCall(Sugar):
    """``f(acc)`` at ``site``, where ``f`` stores ``store`` on ``acc``: each
    evaluation appends the occurrence path it ran in to ``evaluations``.  Its
    ``desugar`` goes through the one wrapper every sugar's does
    (``Sugar.desugar``)."""

    store: object
    site: object
    evaluations: list = field(default_factory=list, compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="test call",
            reason="counts its evaluations",
        )

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor import TermValue
        from sugar_lift_py_tests.floor.named_expression_value import (
            carry_caller_stores,
        )
        from sugar_lift_py_tests.occurrence import current_path
        from sugar_lift_py_tests.outcome import ExitSet

        self.evaluations.append(current_path())
        value = TermValue(len(self.evaluations))
        return ExitSet.completed(carry_caller_stores((self.store,), value))


def _call_in_a_loop_site():
    """The ``f(acc)`` call's fragment in ``for i in (1, 2): y = f(acc)``."""
    function = _function(
        "def g(acc):\n"
        "    for i in (1, 2):\n"
        "        y = f(acc)\n"
    )
    return next(node for node in function.walk() if isinstance(node, Call)).fragment


def test_no_evaluation_of_a_call_is_answered_from_a_record() -> None:
    """``for i in (1, 2): y = f(acc)`` where ``f`` stores on ``acc``: the
    call at its one site is evaluated in each item, in that item, and every
    evaluation of it runs it -- the context holds no record of an earlier
    evaluation to answer it.  A later read of ``y`` is a reference to the
    assignment's key (``Assign.target_evaluations``), never the call."""
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment

    call = _StoringCall(_Tally(), _call_in_a_loop_site())
    ctx = ReduceContext.root(owner="statement-leaves")
    assert not hasattr(ctx, "assigned_values")
    segments = [loop_iteration_segment(_LOOP_TARGET, index) for index in (0, 1)]
    for index, segment in enumerate(segments):
        with entered(segment):
            call.desugar(ctx)
            assert len(call.evaluations) == 2 * index + 1
            call.desugar(ctx)
            assert len(call.evaluations) == 2 * index + 2
    assert [path[-1] for path in call.evaluations] == [
        segment for segment in segments for _run in (0, 1)
    ]


def test_the_ordinary_call_reads_its_receiver_through_the_doors_key() -> None:
    """``r.append(1)`` on a name: the one door evaluates the receiver once,
    and the ordinary call it takes on a value no floor cites reads the
    receiver through the receiver's projection of the statement's key
    (``PathContainerCall.receiver_evaluation``), never the receiver
    evaluated again."""
    rewritten = _function(
        "def f():\n"
        "    r = []\n"
        "    r.append(1)\n"
        "    return r\n"
    ).substitute({})
    calls = [node for node in rewritten.walk() if node.kind == "PathContainerCall"]
    assert calls
    for call in calls:
        key = getattr(call, "receiver_evaluation", None)
        assert isinstance(key, str)
        held = call.fallback.func.value
        assert held.kind == "EvaluationRef"
        assert held.evaluation == key


# ---------------------------------------------------------------------------
# (4) The unroll keeps the iterable's calls before the first item.
# ---------------------------------------------------------------------------


def test_an_unrolled_for_evaluates_a_later_items_call_before_the_first_item():
    # ``break`` leaves after the first item: Python still called ``g`` when
    # it built the list, before the first item.
    rewritten = _function(
        "def f():\n"
        "    acc = []\n"
        "    for x in [1, g(acc)]:\n"
        "        break\n"
        "    return acc\n"
        "def g(a):\n"
        "    a.append(1)\n"
        "    return 0\n"
    ).substitute({})
    stores = [node for node in rewritten.body if isinstance(node, Assign)]
    called = [
        index
        for index, node in enumerate(stores)
        if getattr(node.value, "kind", None) == "Call"
    ]
    first_item = [
        index
        for index, node in enumerate(stores)
        if getattr(node.value, "kind", None) == "Constant"
        and node.value.value == 1
    ]
    assert called, "the later item's call was dropped by the unroll"
    assert first_item
    assert called[0] < first_item[0]


def _unrolled_unpacking_function(body: str):
    """``f`` after substitution: a ``for`` unpacking each item into two
    names over a display whose later item is a call."""
    return _function(
        "def f():\n"
        "    acc = []\n"
        "    for a, b in [(1, 2), g(acc)]:\n"
        f"        {body}\n"
        "    return acc\n"
        "def g(acc):\n"
        "    acc.append(1)\n"
        "    return (3, 4)\n"
    ).substitute({})


def _unrolled_unpacking(body: str):
    """``f``'s assignments and expression statements after substitution:
    the later item's call is evaluated before the first item as an
    expression statement held under the item's evaluation key."""
    rewritten = _unrolled_unpacking_function(body)
    return [node for node in rewritten.body if isinstance(node, (Assign, Expr))]


def _value_kind(node):
    return getattr(node.value, "kind", None)


def test_an_unrolled_unpacking_for_calls_a_later_item_before_the_first_item():
    # ``break`` leaves after the first item: Python still called ``g`` when
    # it built the list, whatever the item's shape -- only the unpack of
    # ``g``'s value belongs to the item that never ran.
    stores = _unrolled_unpacking("break")
    called = [index for index, node in enumerate(stores) if _value_kind(node) == "Call"]
    first_item = [
        index for index, node in enumerate(stores) if _value_kind(node) == "Tuple"
    ]
    assert len(called) == 1, "the later item's call was dropped by the unroll"
    assert first_item
    assert called[0] < first_item[0]


def test_an_unrolled_unpacking_for_unpacks_a_later_item_where_it_is_taken():
    # The later item's unpack reads the call's one evaluation through its key
    # where the item is taken: the call is never evaluated twice, and the
    # unpack (its arity) never runs before the first item's body.
    stores = _unrolled_unpacking("pass")
    called = [index for index, node in enumerate(stores) if _value_kind(node) == "Call"]
    first_item = [
        index for index, node in enumerate(stores) if _value_kind(node) == "Tuple"
    ]
    unpacked = [
        index
        for index, node in enumerate(stores)
        if _value_kind(node) == "EvaluationRef"
    ]
    assert len(called) == 1
    assert first_item and unpacked
    assert called[0] < first_item[0] < unpacked[-1]
    # The call's value is held under the item's evaluation key, and the
    # later item's unpack reads that key.
    held = stores[called[0]]
    assert isinstance(held, Expr)
    assert stores[unpacked[-1]].value.evaluation == held.evaluation


def test_an_unrolled_unpacking_for_makes_up_no_name():
    # The element evaluated before the first item is held under the item's
    # evaluation key: no synthetic Name (``for-item:<i>``) is bound in the
    # user's namespace, for any reader of the rewritten tree's Name targets.
    for body in ("pass", "break"):
        rewritten = _unrolled_unpacking_function(body)
        names = [node.id for node in rewritten.walk() if isinstance(node, Name)]
        assert names
        assert not [name for name in names if name.startswith("for-item:")]
