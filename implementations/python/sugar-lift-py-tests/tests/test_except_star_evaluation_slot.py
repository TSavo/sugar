"""``except* E as eg``: one slot per evaluation, as for ``except E as e``.

Temporal choice 1 (#7661), row-7 map item 5 (#7757 item 7): a read of ``eg``
is the handler's ``EffectRef``. A ``try ... except*`` evaluated more than once
(a loop iteration's copy, a duplicated ``finally``'s exit-path copy) keys each
handler with its own evaluation (``Try._keyed_handlers``), so a read of one
evaluation's ``eg`` is never a sibling's effect group.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import (
    _EVALUATION_OCCURRENCE,
    EffectRef,
    ExceptHandler,
    FunctionDef,
    Try,
    TryStar,
    _Splice,
)
from sugar_source_tree.tree import SourceFile

TRY_STAR = (
    "def f():\n"
    "    try:\n"
    "        raise ValueError\n"
    "    except* ValueError as eg:\n"
    "        x = eg\n"
)
LOOP_TRY_STAR = (
    "def f():\n"
    "    for v in [1, 2]:\n"
    "        try:\n"
    "            raise ValueError\n"
    "        except* ValueError as eg:\n"
    "            x = eg\n"
)


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "except_star_evaluation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _node(function, kind):
    return next(node for node in function.walk() if isinstance(node, kind))


def _statement(result):
    return result.statements[0] if isinstance(result, _Splice) else result


def _handler_read(try_node: TryStar) -> EffectRef:
    (handler,) = try_node.handlers
    (assign,) = handler.body
    assert isinstance(assign.value, EffectRef)
    return assign.value


def test_a_try_star_evaluated_once_keeps_its_source_slot() -> None:
    function = _function(TRY_STAR)
    source_slot = _node(function, ExceptHandler)._effect_slot_id()
    rewritten = function.substitute({})
    (try_node,) = [node for node in rewritten.body if isinstance(node, TryStar)]
    assert try_node.handlers[0]._effect_slot_id() == source_slot
    assert _handler_read(try_node).slot_id == source_slot
    assert not isinstance(getattr(try_node, "evaluation", None), str)


def test_each_evaluation_of_a_try_star_reads_its_own_slot() -> None:
    function = _function(TRY_STAR)
    try_node = _node(function, TryStar)
    source_slot = try_node.handlers[0]._effect_slot_id()
    first = _statement(try_node.substitute({_EVALUATION_OCCURRENCE: ("seg#0",)}))
    second = _statement(try_node.substitute({_EVALUATION_OCCURRENCE: ("seg#1",)}))
    assert isinstance(first, TryStar) and isinstance(second, TryStar)
    slots = [node.handlers[0]._effect_slot_id() for node in (first, second)]
    assert slots[0] != slots[1]
    assert source_slot not in slots
    assert [_handler_read(node).slot_id for node in (first, second)] == slots


def test_a_keyed_try_star_carries_its_evaluation() -> None:
    try_node = _node(_function(TRY_STAR), TryStar)
    keyed = _statement(try_node.substitute({_EVALUATION_OCCURRENCE: ("seg#0",)}))
    assert isinstance(keyed.evaluation, str)
    assert keyed.handlers[0].evaluation == keyed.evaluation
    # A re-substitution keeps the key it was minted under.
    again = _statement(keyed.substitute({}))
    assert again.evaluation == keyed.evaluation
    assert again.handlers[0]._effect_slot_id() == keyed.handlers[0]._effect_slot_id()


def _loop_tries(rewritten) -> list:
    """The ``try ... except*`` statements of the one loop statement's body:
    no rewrite unrolls a loop (#8957), so none stands in the function body."""
    assert not [node for node in rewritten.body if isinstance(node, TryStar)]
    (loop,) = [
        node for node in rewritten.body if node.kind == "LoopRecurrenceStatement"
    ]
    return [
        _statement(node) for node in loop.loop.body if isinstance(_statement(node), TryStar)
    ]


def test_a_try_star_in_a_loop_is_one_statement_with_its_source_slot() -> None:
    # The rewrite does not copy the loop body per item: the ``try`` stands
    # once, keyed as the source occurrence.  Each item's evaluation of it is
    # the reduction's, under that item's occurrence segment
    # (``occurrence.loop_iteration_segment``).
    function = _function(LOOP_TRY_STAR)
    source_slot = _node(function, ExceptHandler)._effect_slot_id()
    (try_node,) = _loop_tries(function.substitute({}))
    assert try_node.handlers[0]._effect_slot_id() == source_slot
    assert _handler_read(try_node).slot_id == source_slot


def test_the_same_source_gives_the_same_try_star_slots() -> None:
    def slots():
        return [
            node.handlers[0]._effect_slot_id()
            for node in _loop_tries(_function(LOOP_TRY_STAR).substitute({}))
        ]

    assert slots() and slots() == slots()


def test_try_and_try_star_key_handlers_the_one_way() -> None:
    try_node = _node(_function(TRY_STAR), TryStar)
    scope = {_EVALUATION_OCCURRENCE: ("seg#0",)}
    (handler,) = Try._keyed_handlers(try_node, scope)
    assert handler.evaluation == try_node._duplicated_evaluation_key(scope)
    assert Try._keyed_handlers(try_node, {}) is try_node.handlers
