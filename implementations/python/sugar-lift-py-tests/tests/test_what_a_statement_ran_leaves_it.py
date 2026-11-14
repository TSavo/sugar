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
- A class statement publishes its body's callee stores to its block
  (``ClassDefinitionValue.extend_scope``) and lays them once in its record.
- A ``for`` the unroll dissolves evaluates its iterable's calls before the
  first item (``For._evaluated_before_the_first_item``), whatever the item's
  shape: an earlier item's ``break`` never drops a later item's call, and a
  later item's unpack still runs where that item is taken.
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.container_mutation import _identity
from sugar_source_tree.nodes import Assign, FunctionDef, Return
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

    receiver = ObjectValue("Box", (), identity="box-1")
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


def test_a_class_body_field_lays_its_callee_store_in_the_body_record() -> None:
    """``class C: y = g(box)`` where ``g`` stored ``box.x``: the class body's
    record carries the store, which the class statement lays before the
    class (``ClassDefinitionValue.body_stores``)."""
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.assigned_value import evaluate_assignment_values
    from sugar_lift_py_tests.sugar.class_definition_sugar import _ClassBodyV1

    ctx, store, _stored = _caller_holding_a_receiver()
    outcome = evaluate_assignment_values(
        (_carrying(store),),
        ctx,
        tail=lambda active, completed: ExitSet.completed(_ClassBodyV1((), ())),
    )
    body = outcome.completed_value()
    assert isinstance(body, _ClassBodyV1)
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


def test_a_class_statement_publishes_its_body_stores_to_its_block() -> None:
    """``class C: y = g(box)``: the statement after the class reads ``box``
    as ``g`` left it, and the class statement's record lays the store once,
    before the class (``ClassDefinitionValue.extend_scope``,
    ``contribution``)."""
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.floor.class_definition_value import (
        ClassDefinitionValue,
    )
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )

    ctx, store, stored = _caller_holding_a_receiver()
    cls = ClassDefinitionValue(
        "C",
        "class-c",
        (),
        None,
        SourceFragmentCoordinateV1("statement_leaves.py", 2, 0, 3, 0),
        body_stores=(store,),
    )
    record = reduce_block_to_exitset(
        (_Answers(ExitSet.completed(cls)),), ctx
    ).completed_value()
    assert record.context.temporal.value_for("box") == stored
    stored_first, laid = record.entries
    assert stored_first == store
    assert laid == cls
    assert laid.body_stores == ()


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


def _unrolled_unpacking(body: str):
    """``f``'s statements after substitution: a ``for`` unpacking each item
    into two names over a display whose later item is a call."""
    rewritten = _function(
        "def f():\n"
        "    acc = []\n"
        "    for a, b in [(1, 2), g(acc)]:\n"
        f"        {body}\n"
        "    return acc\n"
        "def g(acc):\n"
        "    acc.append(1)\n"
        "    return (3, 4)\n"
    ).substitute({})
    return [node for node in rewritten.body if isinstance(node, Assign)]


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
