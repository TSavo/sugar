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
- The exit face of such a copy was still the source line's, shared by every
  copy. It is now keyed per evaluation too, and the derived protocol that
  describes ``__exit__`` is re-keyed onto that face where the sugar is built.
- ``with gen() as (a, b)`` with a generator-based manager lowered no store, so
  ``a``/``b`` were read by spelling afterwards. The store is now lowered as for
  a class-based manager.
- ``with M() as (a, b)`` whose manager nobody seated a row for asked the
  require door during substitution, so it refused before any reader ran. The
  store is now lowered and the refusal is construction's (#7757 entry 8).
"""

from __future__ import annotations

import pytest

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
    Name,
    ObservationRef,
    Return,
    With,
    _Splice,
)
from sugar_source_tree.panic import ContextManagerResolutionConstructionGap
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
WITH_TUPLE_FORMAL = "def f(m):\n    with m as (a, b):\n        pass\n    return a\n"
WITH_IN_LOOP = (
    "def f():\n"
    "    for i in [1, 2]:\n"
    "        with m as x:\n"
    "            y = x\n"
)


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "for_with_target_evaluation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _node(function, kind):
    return next(node for node in function.walk() if isinstance(node, kind))


def _with(result):
    """A ``with`` substituted alone: it publishes what its body left beside
    it (``With._published``)."""
    if isinstance(result, _Splice):
        (result,) = result.statements
    return result


def _keyed(node) -> bool:
    # An iteration's unpack (``a, b = <item>``).  ``x = a`` in the body is
    # keyed too, as every assignment is, but it is no unpack.
    return (
        isinstance(node, Assign)
        and isinstance(getattr(node, "evaluation", None), str)
        and not isinstance(node.targets[0], Name)
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


def test_display_items_are_keyed_per_iteration_too() -> None:
    # A display item is paired by the iteration's own display unpack, keyed
    # as that iteration's evaluation: the target never inlines the member.
    body = _function(FOR_DISPLAYS).substitute({}).body
    unpacks = _unpacks(body)
    assert len(unpacks) == 2
    assert unpacks[0].evaluation != unpacks[1].evaluation
    ret = body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == projection_key(unpacks[-1].evaluation, "b")


def test_every_item_is_keyed_display_or_not() -> None:
    body = _function(FOR_MIXED).substitute({}).body
    unpacks = _unpacks(body)
    assert len(unpacks) == 2
    ret = body[-1]
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == projection_key(unpacks[-1].evaluation, "b")


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
        _with(with_node.substitute({_EVALUATION_OCCURRENCE: (segment,)}))
        for segment in ("seg#0", "seg#1")
    ]


def test_a_with_evaluated_once_keeps_its_source_slots() -> None:
    source = _node(_function(WITH_ONCE), With)
    source_slot = source.items[0]._manager_slot_id()
    with_node = _with(source.substitute({}))
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


def test_each_evaluation_of_a_with_exits_over_its_own_face() -> None:
    source = _node(_function(WITH_ONCE), With)
    source_face = source.items[0]._exit_face_id()
    assert source_face == source.items[0]._source_exit_face_id()
    faces = [node.items[0]._exit_face_id() for node in _copies(source)]
    assert faces[0] != faces[1]
    assert source_face not in faces
    # The derivation's face stays the source occurrence's, once per use site.
    assert {node.items[0]._source_exit_face_id() for node in _copies(source)} == {
        source_face
    }


def test_a_with_evaluated_once_keeps_its_source_face() -> None:
    source = _node(_function(WITH_ONCE), With)
    with_node = _with(source.substitute({}))
    assert with_node.items[0]._exit_face_id() == source.items[0]._exit_face_id()


def _withs(node) -> list[With]:
    return [child for child in node.walk() if isinstance(child, With)]


def test_a_with_in_an_unrolled_loop_has_two_exit_faces_and_two_slots() -> None:
    function = _function(WITH_IN_LOOP)
    (source,) = _withs(function)
    copies = _withs(function.substitute({}))
    assert len(copies) == 2
    items = [node.items[0] for node in copies]
    faces = [item._exit_face_id() for item in items]
    slots = [item._manager_slot_id() for item in items]
    assert len(set(faces)) == 2
    assert len(set(slots)) == 2
    assert source.items[0]._exit_face_id() not in faces
    assert source.items[0]._manager_slot_id() not in slots
    # Each copy's parametric exit arguments name that copy's face.
    for item, face in zip(items, faces, strict=True):
        assert item._make_exit_type_ref().face_id == face
        assert item._make_exit_value_ref().face_id == face
        assert item._make_exit_traceback_ref().face_id == face


# ---------------------------------------------------------------------------
# The protocol that describes __exit__ is keyed over the same face.
# ---------------------------------------------------------------------------


class _FaceProtocol:
    def __init__(self, exit_face_id: str) -> None:
        self.exit_face_id = exit_face_id

    def at_exit_face(self, exit_face_id: str) -> "_FaceProtocol":
        return _FaceProtocol(exit_face_id)


def test_a_with_evaluated_once_keeps_its_derived_protocol() -> None:
    item = _with(_node(_function(WITH_ONCE), With).substitute({})).items[0]
    protocol = _FaceProtocol(item._source_exit_face_id())
    assert With._protocol_at_exit_face(protocol, item) is protocol


def test_each_evaluation_describes_exit_over_its_own_face() -> None:
    source = _node(_function(WITH_ONCE), With)
    protocol = _FaceProtocol(source.items[0]._source_exit_face_id())
    for node in _copies(source):
        item = node.items[0]
        keyed = With._protocol_at_exit_face(protocol, item)
        assert keyed.exit_face_id == item._exit_face_id()
    assert protocol.exit_face_id == source.items[0]._exit_face_id()


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


def test_a_generator_manager_tuple_target_reads_its_projections(
    monkeypatch,
) -> None:
    # ``with gen() as (a, b)``: the manager's contract is its generator frame.
    # The store is lowered as for a class-based manager, so after the with
    # ``a``/``b`` are the store's projections, not their prior state.
    monkeypatch.setattr(With, "_generator_manager_frame", lambda self, item: object())
    with_node = _with(_node(_function(WITH_TUPLE), With).substitute({}))
    assert isinstance(with_node, With)
    item = with_node.items[0]
    store = with_node.body[0]
    assert _keyed(store)
    assert store.value.slot_id == f"{item._manager_slot_id()}#enter_result"
    binding = with_node.substitution_binding({})
    assert set(binding) == {"a", "b"}
    for name in ("a", "b"):
        assert isinstance(binding[name], EvaluationRef)
        assert binding[name].evaluation == projection_key(store.evaluation, name)


def test_an_unseated_tuple_target_lowers_its_store_and_construction_refuses() -> None:
    # Nobody seated a row for ``m``.  Substitution does not ask the require
    # door: the store is lowered onto the enter result, as a simple ``as``
    # name is bound to it, and ``a``/``b`` read its projections after the
    # with.  Constructing the with asks the door and refuses by name.
    function = _function(WITH_TUPLE_FORMAL)
    with_node = _with(_node(function, With).substitute({}))
    assert isinstance(with_node, With)
    item = with_node.items[0]
    store = with_node.body[0]
    assert _keyed(store)
    assert store.value.slot_id == f"{item._manager_slot_id()}#enter_result"
    binding = with_node.substitution_binding({})
    assert set(binding) == {"a", "b"}
    for name in ("a", "b"):
        assert isinstance(binding[name], EvaluationRef)
        assert binding[name].evaluation == projection_key(store.evaluation, name)
    with pytest.raises(ContextManagerResolutionConstructionGap) as refused:
        function.sugar()
    assert refused.value.owner == "With._construct_sugar"


def test_a_generator_manager_store_is_lowered_once(monkeypatch) -> None:
    monkeypatch.setattr(With, "_generator_manager_frame", lambda self, item: object())
    with_node = _node(_function(WITH_TUPLE), With)
    bound = with_node._bind_store_target(with_node.items[0])
    assert len(bound.body) == len(with_node.body) + 1
    assert bound._bind_store_target(bound.items[0]) is bound
