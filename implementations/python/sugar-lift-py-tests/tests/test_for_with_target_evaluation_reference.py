"""``for a, b in ...`` and ``with ... as``: each target reads its own evaluation.

Temporal choice 1 (#7661), inventory item 7 (#7757), after #7886 (``x += e``),
#7911 (the walrus), #7913 (``a, b = f()``) and #7921 (``except``/``raises``
``as e``):

- ``for a, b in [p, q]``: an item that is not a display has no members
  substitution can pair. Before, the unroll refused it. Now each iteration
  opens with its own keyed unpack of its item, and a read of ``a`` is an
  ``EvaluationRef`` to ``a``'s projection of that iteration's evaluation.
- ``with M() as (a, b)``: the store lowered into the body was keyed as one
  evaluation, but after the ``with`` the targets bound nothing, so a read fell
  to the name's prior state. Now they read the store's projections.
- ``with M() as x`` copied per loop iteration (or per ``finally`` exit path)
  shared one manager / enter-result slot across copies. Each copy's item is now
  keyed with its own evaluation, so its slots are its own.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_contract import ENTER_RESULT
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.sugar.dynamic_unpack_assign_sugar import (
    DynamicUnpackAssignSugar,
)
from sugar_lift_py_tests.temporal.temporal_context import (
    EVALUATION_PREFIX,
    projection_key,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import (
    _EVALUATION_OCCURRENCE,
    Assign,
    EvaluationRef,
    FunctionDef,
    ObservationRef,
    Return,
    With,
)
from sugar_source_tree.shadow import rewrite
from sugar_source_tree.tree import SourceFile

FOR_ITEMS = (
    "def f(p, q):\n"
    "    for a, b in [p, q]:\n"
    "        x = a\n"
    "    return b\n"
)
FOR_DISPLAYS = (
    "def f():\n"
    "    for a, b in [(1, 2), (3, 4)]:\n"
    "        x = a\n"
    "    return b\n"
)
FOR_MIXED = (
    "def f(p):\n"
    "    for a, b in [(1, 2), p]:\n"
    "        x = a\n"
    "    return b\n"
)
WITH_ONCE = "def f():\n    with m as x:\n        y = x\n"
WITH_TUPLE = "def f():\n    with m as (a, b):\n        pass\n    return a\n"


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "for_with_target_evaluation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _node(function, kind):
    return next(node for node in function.walk() if isinstance(node, kind))


def _keyed(node) -> bool:
    return isinstance(node, Assign) and isinstance(
        getattr(node, "evaluation", None), str
    )


def _unpacks(body) -> list:
    return [node for node in body if _keyed(node)]


# ---------------------------------------------------------------------------
# for a, b in ...: one keyed unpack per iteration.
# ---------------------------------------------------------------------------


def test_each_iteration_unpacks_its_item_as_its_own_evaluation() -> None:
    body = _function(FOR_ITEMS).substitute({}).body
    unpacks = _unpacks(body)
    assert len(unpacks) == 2
    first, second = unpacks
    assert first.evaluation.startswith(EVALUATION_PREFIX)
    assert first.evaluation != second.evaluation


def test_a_read_in_the_body_is_its_iterations_projection() -> None:
    body = _function(FOR_ITEMS).substitute({}).body
    unpacks = _unpacks(body)
    reads = [
        node.value for node in body if isinstance(node, Assign) and not _keyed(node)
    ]
    assert len(reads) == 2
    for unpack, read in zip(unpacks, reads, strict=True):
        assert isinstance(read, EvaluationRef)
        assert read.evaluation == projection_key(unpack.evaluation, "a")
        assert read.name == "a"


def test_a_read_after_the_loop_is_the_last_iterations_projection() -> None:
    body = _function(FOR_ITEMS).substitute({}).body
    unpacks = _unpacks(body)
    ret = body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == projection_key(unpacks[-1].evaluation, "b")


def test_the_same_source_gives_the_same_iteration_keys() -> None:
    def keys():
        body = _function(FOR_ITEMS).substitute({}).body
        return [node.evaluation for node in _unpacks(body)]

    assert keys() == keys()


def test_display_items_still_pair_by_substitution() -> None:
    body = _function(FOR_DISPLAYS).substitute({}).body
    assert not _unpacks(body)
    ret = body[-1]
    assert isinstance(ret, Return)
    assert not isinstance(ret.value, EvaluationRef)


def test_only_a_non_display_item_is_unpacked() -> None:
    body = _function(FOR_MIXED).substitute({}).body
    unpacks = _unpacks(body)
    assert len(unpacks) == 1
    ret = body[-1]
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == projection_key(unpacks[0].evaluation, "b")


def test_the_iteration_unpack_sugar_carries_its_key() -> None:
    statement = _function(FOR_ITEMS).sugar().statements[0]
    assert isinstance(statement, DynamicUnpackAssignSugar)
    assert isinstance(statement.evaluation, str)
    assert statement.evaluation.startswith(EVALUATION_PREFIX)


# ---------------------------------------------------------------------------
# with ... as x: one slot per evaluation of the with.
# ---------------------------------------------------------------------------


def _body_read(with_node: With) -> ObservationRef:
    (assign,) = with_node.body
    assert isinstance(assign.value, ObservationRef)
    return assign.value


def _copies(with_node: With) -> list[With]:
    """Two evaluations of one with, as two unrolled iterations substitute it
    (``For.substitute`` / ``_iteration_scope``)."""
    return [
        with_node.substitute({_EVALUATION_OCCURRENCE: (segment,)})
        for segment in ("seg#0", "seg#1")
    ]


def test_a_with_evaluated_once_keeps_its_source_slots() -> None:
    source = _node(_function(WITH_ONCE), With)
    source_slot = source.items[0]._manager_slot_id()
    with_node = source.substitute({})
    assert isinstance(with_node, With)
    assert getattr(with_node.items[0], "evaluation", None) is None
    assert with_node.items[0]._manager_slot_id() == source_slot
    assert _body_read(with_node).slot_id == f"{source_slot}#enter_result"


def test_each_evaluation_of_a_with_has_its_own_slots() -> None:
    source = _node(_function(WITH_ONCE), With)
    source_slot = source.items[0]._manager_slot_id()
    copies = _copies(source)
    slots = [node.items[0]._manager_slot_id() for node in copies]
    assert slots[0] != slots[1]
    assert source_slot not in slots
    # The `as x` read in each copy is that copy's enter result.
    assert [_body_read(node).slot_id for node in copies] == [
        f"{slot}#enter_result" for slot in slots
    ]


def test_a_duplicated_with_keys_its_item_with_its_own_evaluation() -> None:
    for node in _copies(_node(_function(WITH_ONCE), With)):
        assert isinstance(node.evaluation, str)
        assert node.items[0].evaluation == node.evaluation


def test_the_same_source_gives_the_same_with_slots() -> None:
    def slots():
        source = _node(_function(WITH_ONCE), With)
        return [node.items[0]._manager_slot_id() for node in _copies(source)]

    assert slots() == slots()


def test_the_exit_face_stays_the_source_occurrences() -> None:
    # The manager summary derivation states the protocol's exit over the
    # source item's face; the sugar's face facts must name the same face.
    source = _node(_function(WITH_ONCE), With)
    source_face = source.items[0]._exit_face_id()
    assert [node.items[0]._exit_face_id() for node in _copies(source)] == [
        source_face,
        source_face,
    ]


# ---------------------------------------------------------------------------
# with ... as (a, b): after the with, each target is its store's projection.
# ---------------------------------------------------------------------------


def _with_lowered_store(with_node: With) -> With:
    """The with as ``_bind_store_target`` lowers it, store substituted."""
    item = with_node.items[0]
    enter_slot = f"{item._manager_slot_id()}#enter_result"
    store = with_node._make_assign(
        item.optional_vars, item._make_observation_ref(enter_slot, ENTER_RESULT)
    )
    store = store.substitute({})
    return rewrite(with_node, body=(store, *with_node.body))


def test_a_read_after_a_with_tuple_target_is_its_projection() -> None:
    with_node = _with_lowered_store(_node(_function(WITH_TUPLE), With))
    store = with_node.body[0]
    assert _keyed(store)
    binding = with_node.substitution_binding({})
    assert set(binding) == {"a", "b"}
    for name in ("a", "b"):
        assert isinstance(binding[name], EvaluationRef)
        assert binding[name].evaluation == projection_key(store.evaluation, name)


def test_a_with_tuple_target_without_its_store_binds_nothing() -> None:
    with_node = _node(_function(WITH_TUPLE), With)
    assert with_node.substitution_binding({}) is None
