"""``except ... as e`` / ``with pytest.raises(...) as e``: one slot per evaluation.

Temporal choice 1 (#7661), row-7 map item 5 (#7757): a read of ``e`` is a
reference to its statement's evaluation. Substitution already rewrites it to
the handler's ``EffectRef`` or the with item's enter result; a statement
evaluated more than once (a loop iteration's copy, a duplicated ``finally``'s
exit-path copy) now gives each evaluation its own slot, so a read of one
evaluation's ``e`` is never a sibling's effect.
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import (
    _EVALUATION_OCCURRENCE,
    EffectRef,
    ExceptHandler,
    FunctionDef,
    Statement,
    Try,
    With,
    _Splice,
)
from sugar_source_tree.shadow import rewrite_with_leaves
from sugar_source_tree.tree import SourceFile

TRY = (
    "def f():\n"
    "    try:\n"
    "        raise ValueError\n"
    "    except ValueError as e:\n"
    "        x = e\n"
)
LOOP_TRY = (
    "def f():\n"
    "    for v in [1, 2]:\n"
    "        try:\n"
    "            raise ValueError\n"
    "        except ValueError as e:\n"
    "            x = e\n"
)
WITH = "def f():\n    with m as e:\n        pass\n"


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "effect_binding_evaluation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _node(function, kind):
    return next(node for node in function.walk() if isinstance(node, kind))


def _statement(result):
    return result.statements[0] if isinstance(result, _Splice) else result


def _handler_read(try_node: Try) -> EffectRef:
    (handler,) = try_node.handlers
    (assign,) = handler.body
    assert isinstance(assign.value, EffectRef)
    return assign.value


def test_a_try_evaluated_once_keeps_its_source_slot() -> None:
    function = _function(TRY)
    source_slot = _node(function, ExceptHandler)._effect_slot_id()
    rewritten = function.substitute({})
    (try_node,) = [node for node in rewritten.body if isinstance(node, Try)]
    assert try_node.handlers[0]._effect_slot_id() == source_slot
    assert _handler_read(try_node).slot_id == source_slot


def test_each_evaluation_of_a_try_reads_its_own_slot() -> None:
    function = _function(TRY)
    try_node = _node(function, Try)
    source_slot = try_node.handlers[0]._effect_slot_id()
    first = _statement(try_node.substitute({_EVALUATION_OCCURRENCE: ("seg#0",)}))
    second = _statement(try_node.substitute({_EVALUATION_OCCURRENCE: ("seg#1",)}))
    slots = [node.handlers[0]._effect_slot_id() for node in (first, second)]
    assert slots[0] != slots[1]
    assert source_slot not in slots
    assert [_handler_read(node).slot_id for node in (first, second)] == slots


def _loop_tries(rewritten) -> list:
    """The ``try`` statements of the one loop statement's body: no rewrite
    unrolls a loop (#8957), so none stands in the function body."""
    assert not [node for node in rewritten.body if isinstance(node, Try)]
    (loop,) = [
        node for node in rewritten.body if node.kind == "LoopRecurrenceStatement"
    ]
    return [
        _statement(node) for node in loop.loop.body if isinstance(_statement(node), Try)
    ]


def test_a_try_in_a_loop_is_one_statement_with_its_source_slot() -> None:
    # The rewrite does not copy the loop body per item: the ``try`` stands
    # once, keyed as the source occurrence.  Each item's evaluation of it is
    # the reduction's, under that item's occurrence segment
    # (``occurrence.loop_iteration_segment``).
    function = _function(LOOP_TRY)
    source_slot = _node(function, ExceptHandler)._effect_slot_id()
    (try_node,) = _loop_tries(function.substitute({}))
    assert try_node.handlers[0]._effect_slot_id() == source_slot
    assert _handler_read(try_node).slot_id == source_slot


def test_the_same_source_gives_the_same_slots() -> None:
    def slots():
        return [
            node.handlers[0]._effect_slot_id()
            for node in _loop_tries(_function(LOOP_TRY).substitute({}))
        ]

    assert slots() and slots() == slots()


def test_a_statement_evaluated_once_is_not_keyed() -> None:
    with_node = _node(_function(WITH), With)
    assert with_node._keyed_evaluation(with_node, {}) is with_node
    assert with_node._evaluation_slot("slot") == "slot"


def test_a_duplicated_statement_is_keyed() -> None:
    with_node = _node(_function(WITH), With)
    keyed = with_node._keyed_evaluation(
        with_node, {_EVALUATION_OCCURRENCE: ("seg#0",)}
    )
    assert isinstance(keyed, With)
    assert isinstance(keyed.evaluation, str)
    assert keyed._evaluation_slot("slot") != "slot"


def test_each_evaluation_of_a_with_reads_its_own_slot() -> None:
    # A with constructs from its head alone (#8491): the effect-boundary
    # observation slot is gone, and what ``as e`` reads is the item's
    # manager slot (its enter result is ``<slot>#enter_result``).  Each
    # evaluation of a duplicated with keys that slot, never a sibling's.
    with_node = _node(_function(WITH), With)
    source_slot = with_node.items[0]._manager_slot_id()
    slots = []
    for key in ("evaluation:one", "evaluation:two"):
        # With.substitute keys the item with the with's evaluation; the
        # slot is read off the keyed item.
        item = rewrite_with_leaves(with_node.items[0], {"evaluation": key})
        slots.append(item._manager_slot_id())
    assert slots[0] != slots[1]
    assert source_slot not in slots


def test_an_unkeyed_slot_is_the_source_slot() -> None:
    assert Statement._evaluation_slot(SimpleNamespace(), "slot") == "slot"
