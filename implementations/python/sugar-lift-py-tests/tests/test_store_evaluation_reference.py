"""A store and a call's object are read through their statement's key
(temporal choice 1, #7661; #7757 item 7, after #7958).

#7958 keyed every Name an assignment binds.  Three reads still evaluated
the right-hand side again where they were read:

1. ``o.x = v`` threaded ``v`` into later reads of the place: every read of
   ``o``, or of ``o.x``, after the one field store, whatever the receiver
   (``ReceiverFieldStoreState``).  The
   store now evaluates ``v`` once and binds it under its statement's key
   (``KeyedStoreSugar``); the read is a reference to that key (``place``).
2. ``d[k] = v`` on a decided dict rebound ``d`` to a projection of the
   mutating call, which reduced the call (and ``v``) again at every read.
   The statement binds the call's pair under its key
   (``ContainerMutationStatementSugar``); the projection reads it there.
3. A call's result kept as its object identity (``OpaqueObjectStateV1``,
   ``Assign.refine_binding_entries``) reduced its call again at every read.
   It reads the assignment's key, as the name's reference does: ``r =
   p.read()`` is the one mutation door's statement (``p.read()`` may change
   ``p``), which writes ``r`` under the assignment's projection of its key
   for ``r`` (``container_mutation._name_write``).

The residue of #7976, each a second way to obtain a value:

4. A path mutation (``d['a'].append(x)``, ``path_mutation_statement``) ran
   its mutating call again at every read of ``d``.  The statement binds the
   call's pair under its key; the root after it reads the pair there.
5. An object a constructor call built (``ObjectPlaceStateV1``) was read as
   the value computed at substitution, and a field a later store put there
   as the stored expression computed at substitution.  The object reads its
   assignment's key; the field reads the store statement's key.
6. ``with cm:`` over a call result a name holds evaluated the call's
   operands again at the ``with``.  It reads the assignment's key.

The residue of #7990:

7. A read of the whole object after a field store read the assignment's
   key alone: the object without the store.  It reads the object's latest
   state, every keyed field store folded over the assignment's key.
8. A path's root (``d`` in ``d['a'].append(x)``) evaluated the display the
   name was given at every read.  It reads the name's key.
9. The constructor call and every stored value were reduced at
   substitution as identity testimony.  The testimony names the expression
   (the key reference's ``of``); nothing is reduced at substitution.

The residue of #7998:

10. A subscript key was reduced at substitution to decide which field a
    store or read names, and the store's key replaced by that value.  The
    field is the key expression's ground value (a literal, or a key
    reference whose ``of`` is one); a key that is not ground names no known
    field, and a store under it leaves every field unknown.

The residue of #8004:

11. ``o[-1]`` named no field (a unary minus over a literal is not a
    literal), and a dict display's keys were decided by literal only.  Both
    ask the key expression's ground value (``ground_subscript_key``).

Found by #8010:

12. A chained store (``a = o.x = v``, ``a = d[k] = v``) and an unpack's
    store leaf (``a, o.x = p, q``) carried no state into later reads of the
    object: a later ``o.x``, ``d[k]`` or ``xs`` read the state from before
    the store.  Each store target is now ``target = v``'s own statement
    (``Assign._store_statements``), threaded left to right.
"""

from __future__ import annotations

from pathlib import Path

from frame_fresh import fresh
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ListValue, ObjectValue, TermValue
from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.sugar.assign_sugar import KeyedStoreSugar
from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
    ContainerMutationStatementSugar,
    PathAfterCallSugar,
)
from sugar_lift_py_tests.sugar.collection_sugar import DictSugar
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.receiver_field_store_state_sugar import (
    ReceiverFieldStoreStateSugar,
)
from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
    ReceiverFieldStoreSugar,
)
from sugar_lift_py_tests.temporal.temporal_context import projection_key
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.nodes import (
    AnnAssign,
    Assign,
    ContainerMutationStatement,
    EvaluationRef,
    FunctionDef,
    Name,
    ObjectPlaceStateV1,
    PathAfterCall,
    PathContainerCall,
    ReceiverFieldStoreState,
    ReceiverFieldStoreStatement,
    Return,
    _occurrence_testimony,
    ground_subscript_key,
)
from sugar_source_tree.container_mutation import _display_member
from sugar_source_tree.tree import SourceFile

ONE = TermValue(1)

# 1. A field store: the read is the store's key, never ``x`` again.
FIELD = (
    "class C:\n"
    "    pass\n"
    "\n"
    "def f():\n"
    "    o = C()\n"
    "    x = 1\n"
    "    o.x = x\n"
    "    x += 1\n"
    "    return o.x\n"
)
# 1. A field store on a coordinate receiver, read by a later ``self.x``.
INITIALIZER_FIELD = (
    "class C:\n"
    "    def __init__(self, x):\n"
    "        self.x: int = x\n"
    "        x += 1\n"
    "        self.y = self.x\n"
)
# 2. A subscript store.
SUBSCRIPT = (
    "def f():\n"
    "    d = {}\n"
    "    x = 1\n"
    "    d['k'] = x\n"
    "    x += 1\n"
    "    return d['k']\n"
)
# 3. A name bound to a call's result, read twice.
CALL_READ_TWICE = "def f(p):\n    r = p.read()\n    return (r, r)\n"
# 4. A path mutation, its operand rebound after it.
PATH = (
    "def f():\n"
    "    d = {'a': []}\n"
    "    x = 1\n"
    "    d['a'].append(x)\n"
    "    x += 1\n"
    "    return d['a'][0]\n"
)
# 5. An object a constructor call built, and a field a later store put there.
PLACE = (
    "class Box:\n"
    "    pass\n"
    "\n"
    "def f():\n"
    "    box = Box()\n"
    "    x = 1\n"
    "    box.size: int = x\n"
    "    x += 1\n"
    "    return box.size\n"
)
# 7. The whole object read after a field store, its operand rebound after it.
PLACE_OBJECT = (
    "class Box:\n"
    "    pass\n"
    "\n"
    "def f():\n"
    "    box = Box()\n"
    "    x = 1\n"
    "    box.size: int = x\n"
    "    x += 1\n"
    "    return box\n"
)
# 8. A path's root read twice after a path mutation.
PATH_ROOT_TWICE = (
    "def f():\n"
    "    d = {'a': []}\n"
    "    d['a'].append(1)\n"
    "    return (d, d)\n"
)
# 10. A subscript store and read on an object place, by a literal key.
PLACE_ITEM = (
    "class Box:\n"
    "    pass\n"
    "\n"
    "def f():\n"
    "    box = Box()\n"
    "    box['a'] = 1\n"
    "    return box['a']\n"
)
# 10. The store's key is a name holding a literal.
PLACE_ITEM_BY_NAME = (
    "class Box:\n"
    "    pass\n"
    "\n"
    "def f():\n"
    "    box = Box()\n"
    "    k = 'a'\n"
    "    box[k] = 1\n"
    "    return box['a']\n"
)
# 10. The store's key is a call: not ground.
PLACE_ITEM_BY_CALL = (
    "class Box:\n"
    "    pass\n"
    "\n"
    "def g():\n"
    "    return 'a'\n"
    "\n"
    "def f():\n"
    "    box = Box()\n"
    "    box['a'] = 0\n"
    "    box[g()] = 1\n"
    "    return box['a']\n"
)
# 11. A negative int key: a unary minus over a literal.
PLACE_ITEM_NEGATIVE = (
    "class Box:\n"
    "    pass\n"
    "\n"
    "def f():\n"
    "    box = Box()\n"
    "    box[-1] = 1\n"
    "    return box[-1]\n"
)
# 11. A dict display whose key is a name holding a literal.
DICT_DISPLAY_BY_NAME = "def f():\n    k = 'a'\n    return {k: [1]}\n"


def _tree(source: str, context) -> SourceFile:
    return SourceFile(
        (source, "store_evaluation.py", blake3_512_of(source.encode())),
        construction_context=context,
    )


def _function(source: str, name: str = "f", *, context=None) -> FunctionDef:
    tree = _tree(
        source,
        context or TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )


def _outcome(tmp_path: Path, source: str, stem: str, name: str = "f"):
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    functions = SourceFile(
        path_source(str(path)),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    ).functions()
    function = next(node for node in functions if node.name == name)
    return function.sugar().desugar(None)


def _returned(outcome) -> list:
    found: list = []

    def visit(value) -> None:
        if isinstance(value, (ReturnValue, GuardedReturn)):
            found.append(value.value)
            return
        for entry in getattr(value, "statements", ()) or ():
            visit(entry)
        record = getattr(value, "record", None)
        if record is not None:
            visit(record)

    assert isinstance(outcome, ExitSet), outcome
    for exit_ in outcome.exits:
        if isinstance(exit_, Completed):
            visit(exit_.value)
    return found


# ---------------------------------------------------------------------------
# 1. ``o.x = x``: a later read of the place reads the store's key.
# ---------------------------------------------------------------------------


def test_a_field_store_post_state_holds_the_stores_key() -> None:
    body = _function(FIELD).substitute({}).body
    store = next(node for node in body if isinstance(node, ReceiverFieldStoreStatement))
    assert isinstance(store.evaluation, str)
    # The statement evaluates ``x`` itself, once.
    assert store.value.kind == "EvaluationRef"
    assert not getattr(store.value, "place", False)
    ret = body[-1]
    assert isinstance(ret, Return)
    states = [
        node for node in ret.value.walk() if isinstance(node, ReceiverFieldStoreState)
    ]
    assert states
    for state in states:
        # The read holds the store's key, never ``x``'s reference.
        assert state.value.kind == "EvaluationRef"
        assert state.value.place is True
        assert state.value.evaluation == store.evaluation


def test_a_field_store_sugar_binds_its_key() -> None:
    statements = _function(FIELD).sugar().statements
    keyed = [sugar for sugar in statements if isinstance(sugar, KeyedStoreSugar)]
    assert len(keyed) == 1
    (store,) = keyed
    # The one field store stores the value read through the statement's key.
    assert isinstance(store.store, ReceiverFieldStoreSugar)
    stored = store.store.value
    assert isinstance(stored, EvaluationRefSugar)
    assert stored.place
    assert stored.evaluation == store.evaluation


def test_a_field_read_after_a_rebind_is_the_old_value(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, FIELD, "field"))
    assert returned == [ONE], returned


def test_a_coordinate_receiver_field_read_is_the_stores_key() -> None:
    initializer = _function(
        INITIALIZER_FIELD,
        "__init__",
        context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    body = initializer.substitute({}).body
    # ``self.x: int = x`` is the store ``self.x = x`` (#7757): the one field
    # store its substitution makes, whatever the receiver is.
    annotated = next(
        node
        for node in body
        if isinstance(node, ReceiverFieldStoreStatement)
        and node.post_state.attr == "x"
    )
    assert isinstance(annotated.evaluation, str)
    # ``self.y = self.x``: its right-hand side reads ``self`` after
    # ``self.x: int = x``, whose field holds that statement's key, never ``x``
    # (rebound since).
    read = body[-1].value
    assert read.kind == "Attribute"
    states = [
        node for node in read.walk() if isinstance(node, ReceiverFieldStoreState)
    ]
    assert any(
        state.attr == "x"
        and state.value.kind == "EvaluationRef"
        and state.value.place is True
        and state.value.evaluation == annotated.evaluation
        for state in states
    )


def test_a_coordinate_receiver_field_store_binds_its_key() -> None:
    initializer = _function(
        INITIALIZER_FIELD,
        "__init__",
        context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    store = initializer.sugar().statements[0]
    assert isinstance(store, KeyedStoreSugar)
    assert isinstance(store.store, ReceiverFieldStoreSugar)
    assert isinstance(store.store.value, EvaluationRefSugar)
    assert store.store.value.place
    assert store.store.value.evaluation == store.evaluation


# ---------------------------------------------------------------------------
# 2. ``d['k'] = x``: a later read of ``d`` reads the statement's key.
# ---------------------------------------------------------------------------


def test_a_subscript_store_projection_reads_the_statements_key() -> None:
    # ``d['k'] = x`` on a name is the one mutation door's statement since
    # #8096, whatever ``d`` was given: ``d`` after it is the object after the
    # ``__setitem__`` call (``PathAfterCall``), read through the statement's
    # key, as a path mutation's root is (``test_a_path_mutation_reads_the_
    # statements_key``) and as the item stores below read it.
    body = _function(SUBSCRIPT).substitute({}).body
    mutation = next(
        node for node in body if isinstance(node, ContainerMutationStatement)
    )
    assert isinstance(mutation.evaluation, str)
    ret = body[-1]
    assert isinstance(ret, Return)
    afters = [node for node in ret.value.walk() if isinstance(node, PathAfterCall)]
    assert afters
    for after in afters:
        assert after.evaluation == mutation.evaluation
        pair = after.sugar().call
        # The pair is read through the key, never the call evaluated again.
        assert isinstance(pair, EvaluationRefSugar)
        assert pair.place
        assert pair.evaluation == mutation.evaluation


def test_a_subscript_store_statement_binds_its_key() -> None:
    statements = _function(SUBSCRIPT).sugar().statements
    mutation = next(
        sugar
        for sugar in statements
        if isinstance(sugar, ContainerMutationStatementSugar)
    )
    assert isinstance(mutation.evaluation, str)


def test_a_subscript_read_after_a_rebind_is_the_old_value(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, SUBSCRIPT, "subscript"))
    assert returned == [ONE], returned


# ---------------------------------------------------------------------------
# 3. ``r = p.read()`` read twice: the assignment's key, never the call again.
# ---------------------------------------------------------------------------


def test_a_call_result_read_twice_reads_the_assignments_key() -> None:
    # ``p.read()`` may change ``p``: ``r = p.read()`` is the one mutation
    # door's statement (``name_mutation_statement``).  It evaluates the call
    # once and writes ``r`` under the assignment's projection of its key for
    # ``r``, as an ``Assign`` binds each target (``_name_write``).
    body = _function(CALL_READ_TWICE).substitute({}).body
    mutation = next(
        node for node in body if isinstance(node, ContainerMutationStatement)
    )
    assert isinstance(mutation.evaluation, str)
    key = projection_key(mutation.evaluation, "r")
    assert ("r", key) in mutation.written_keys()
    # The statement's sugar binds the call's value under that key.
    statement = mutation.sugar()
    assert isinstance(statement, ContainerMutationStatementSugar)
    assert key in {bound for bound, _index in statement.result_evaluations}
    ret = body[-1]
    assert isinstance(ret, Return)
    reads = ret.value.elts
    assert len(reads) == 2
    for read in reads:
        assert isinstance(read, EvaluationRef)
        assert read.evaluation == key
        sugar = read.sugar()
        # The key, not a second term for the call.
        assert isinstance(sugar, EvaluationRefSugar)
        assert sugar.evaluation == key


# ---------------------------------------------------------------------------
# 4. ``d['a'].append(x)``: a later read of ``d`` reads the statement's key.
# ---------------------------------------------------------------------------


def test_a_path_mutation_reads_the_statements_key() -> None:
    body = _function(PATH).substitute({}).body
    mutation = next(
        node for node in body if isinstance(node, ContainerMutationStatement)
    )
    assert isinstance(mutation.evaluation, str)
    ret = body[-1]
    assert isinstance(ret, Return)
    afters = [node for node in ret.value.walk() if isinstance(node, PathAfterCall)]
    assert afters
    for after in afters:
        assert after.evaluation == mutation.evaluation
        pair = after.sugar().call
        # The pair is read through the key: no second term for the call.
        assert isinstance(pair, EvaluationRefSugar)
        assert pair.place
        assert pair.evaluation == mutation.evaluation


def test_a_path_mutation_statement_binds_its_key() -> None:
    statements = _function(PATH).sugar().statements
    mutation = next(
        sugar
        for sugar in statements
        if isinstance(sugar, ContainerMutationStatementSugar)
    )
    assert isinstance(mutation.evaluation, str)


def test_a_path_read_after_a_rebind_is_the_old_value(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, PATH, "path"))
    assert returned == [ONE], returned


# ---------------------------------------------------------------------------
# 5. ``box = Box()``; ``box.size: int = x``: the object reads its
#    assignment's key, the field reads the store's key.
# ---------------------------------------------------------------------------


def _place_body():
    return _function(PLACE).substitute({}).body


def test_an_object_place_reads_its_assignments_key() -> None:
    body = _place_body()
    assign = next(
        node
        for node in body
        if isinstance(node, Assign)
        and isinstance(node.targets[0], Name)
        and node.targets[0].id == "box"
    )
    # The statement keeps its call: it evaluates it here, once.
    assert assign.value.kind == "Call"
    key = projection_key(assign.evaluation, "box")
    states = [
        node
        for statement in body
        for node in statement.walk()
        if isinstance(node, ObjectPlaceStateV1)
    ]
    assert states
    for state in states:
        assert state.evaluation == key
        sugar = state.sugar()
        # Every store on the object so far, over the key: never the
        # constructed value computed at substitution.
        while isinstance(sugar, ReceiverFieldStoreStateSugar):
            sugar = sugar.receiver
        assert isinstance(sugar, EvaluationRefSugar)
        assert sugar.evaluation == key


def test_an_object_place_field_read_is_the_stores_key() -> None:
    # ``box.size: int = x`` is the store ``box.size = x`` (#7757): the one
    # receiver field store, whose post-state every later read of ``box``
    # reads.
    body = _place_body()
    store = next(node for node in body if isinstance(node, ReceiverFieldStoreStatement))
    assert isinstance(store.evaluation, str)
    # The statement evaluates ``x`` itself, once.
    assert store.value.kind == "EvaluationRef"
    assert not getattr(store.value, "place", False)
    ret = body[-1]
    assert isinstance(ret, Return)
    states = [
        node for node in ret.value.walk() if isinstance(node, ReceiverFieldStoreState)
    ]
    assert states
    for state in states:
        # The read holds the store's key, never ``x``'s reference.
        assert state.value.kind == "EvaluationRef"
        assert state.value.place is True
        assert state.value.evaluation == store.evaluation


def test_an_object_place_store_binds_its_key() -> None:
    statements = _function(PLACE).sugar().statements
    keyed = [sugar for sugar in statements if isinstance(sugar, KeyedStoreSugar)]
    assert len(keyed) == 1
    (store,) = keyed
    assert isinstance(store.store, ReceiverFieldStoreSugar)
    stored = store.store.value
    assert isinstance(stored, EvaluationRefSugar)
    assert stored.place
    assert stored.evaluation == store.evaluation


def test_an_object_place_read_after_a_rebind_is_the_old_value(
    tmp_path: Path,
) -> None:
    returned = _returned(_outcome(tmp_path, PLACE, "place"))
    assert returned == [ONE], returned


# ---------------------------------------------------------------------------
# 7. ``box.size: int = x``; ``return box``: the object read carries the field.
# ---------------------------------------------------------------------------


def test_an_object_read_after_a_field_store_folds_the_store() -> None:
    body = _function(PLACE_OBJECT).substitute({}).body
    assign = next(
        node
        for node in body
        if isinstance(node, Assign)
        and isinstance(node.targets[0], Name)
        and node.targets[0].id == "box"
    )
    store = next(node for node in body if isinstance(node, ReceiverFieldStoreStatement))
    ret = body[-1]
    assert isinstance(ret, Return)
    states = [
        node for node in ret.value.walk() if isinstance(node, ReceiverFieldStoreState)
    ]
    assert states
    for state in states:
        sugar = state.sugar()
        # The store's field, read through the store's key, over the object as
        # its constructor call left it, read through the assignment's key.
        assert isinstance(sugar, ReceiverFieldStoreStateSugar)
        assert sugar.attr == "size"
        assert isinstance(sugar.value, EvaluationRefSugar)
        assert sugar.value.place
        assert sugar.value.evaluation == store.evaluation
        assert isinstance(sugar.receiver, EvaluationRefSugar)
        assert sugar.receiver.evaluation == projection_key(assign.evaluation, "box")


def test_an_object_read_after_a_field_store_carries_the_field(
    tmp_path: Path,
) -> None:
    returned = _returned(_outcome(tmp_path, PLACE_OBJECT, "place_object"))
    assert len(returned) == 1, returned
    (value,) = returned
    assert isinstance(value, ObjectValue), value
    # The value the store completed with (1), never the object without it
    # and never ``x`` read again after its rebind.
    assert [field.value for field in value.fields if field.name == "size"] == [ONE]


# ---------------------------------------------------------------------------
# 8. ``d['a'].append(1)``; ``return (d, d)``: the root is read through its key.
# ---------------------------------------------------------------------------


def test_a_path_root_is_read_through_its_key() -> None:
    body = _function(PATH_ROOT_TWICE).substitute({}).body
    assign = next(
        node
        for node in body
        if isinstance(node, Assign)
        and isinstance(node.targets[0], Name)
        and node.targets[0].id == "d"
    )
    key = projection_key(assign.evaluation, "d")
    ret = body[-1]
    assert isinstance(ret, Return)
    afters = [node for node in ret.value.walk() if isinstance(node, PathAfterCall)]
    assert afters
    for after in afters:
        # The root as the statement read it: ``d``'s key, never the display.
        assert after.root.kind == "EvaluationRef"
        assert after.root.evaluation == key
        sugar = after.sugar()
        assert isinstance(sugar, PathAfterCallSugar)
        assert isinstance(sugar.root, EvaluationRefSugar)
        assert sugar.root.evaluation == key


def test_a_path_root_read_twice_evaluates_its_root_once(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "path_root_twice.py"
    path.write_text(PATH_ROOT_TWICE, encoding="utf-8")
    functions = SourceFile(
        path_source(str(path)),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    ).functions()
    sugar = next(node for node in functions if node.name == "f").sugar()
    original = DictSugar.desugar
    evaluations = 0

    def counted(self, ctx=None):
        nonlocal evaluations
        evaluations += 1
        return original(self, ctx)

    monkeypatch.setattr(DictSugar, "desugar", counted)
    sugar.desugar(None)
    # Once, at ``d = {'a': []}``; neither read of ``d`` evaluates it again.
    assert evaluations == 1, evaluations


# ---------------------------------------------------------------------------
# 9. No constructor call and no stored value is reduced at substitution.
# ---------------------------------------------------------------------------


def test_no_constructor_call_is_reduced_at_substitution() -> None:
    body = _place_body()
    assign = next(
        node
        for node in body
        if isinstance(node, Assign)
        and isinstance(node.targets[0], Name)
        and node.targets[0].id == "box"
    )
    store = next(node for node in body if isinstance(node, ReceiverFieldStoreStatement))
    states = [
        node
        for statement in body
        for node in statement.walk()
        if isinstance(node, ObjectPlaceStateV1)
    ]
    assert states
    for state in states:
        # No constructed value rides the state: its testimony names the
        # constructor call, the key reference's ``of``.
        assert getattr(state, "constructed_value", None) is None
        assert state.base.kind == "Call"
        assert state.base.span == assign.value.span
        assert (
            state.construction_testimony.cid
            == _occurrence_testimony(state.base).cid
        )
        state.validate_identity()
    # The stored value is the store statement's own key reference: nothing
    # was reduced for it at substitution.
    assert store.value.kind == "EvaluationRef"


# ---------------------------------------------------------------------------
# 10. ``box[k] = 1``: an item store on a name is the one mutation door's
#     statement (``container_mutation.name_mutation_statement``, #8096),
#     whatever ``box`` was given; the receiver's value decides
#     ``__setitem__`` at reduce.  The statement keeps its key expression,
#     never the key reduced at substitution, and a later read of ``box``
#     reads the object after the store through the statement's key.
# ---------------------------------------------------------------------------


def _item_stores(body) -> list:
    """``(statement, call)`` for each item store: the door's statement and
    the one ``__setitem__`` operation it evaluates (``evaluated[0]``)."""
    return [
        (node, node.evaluated[0])
        for node in body
        if isinstance(node, ContainerMutationStatement)
        and node.evaluated
        and isinstance(node.evaluated[0], PathContainerCall)
        and node.evaluated[0].method == "__setitem__"
    ]


def _reads_after(read, store) -> None:
    """``read`` reads the object after ``store`` through the statement's key:
    the call's pair is read there, never the call (and its key and value)
    evaluated again."""
    afters = [node for node in read.walk() if isinstance(node, PathAfterCall)]
    assert any(after.evaluation == store.evaluation for after in afters), afters
    for after in afters:
        pair = after.sugar().call
        assert isinstance(pair, EvaluationRefSugar)
        assert pair.place
        assert pair.evaluation == after.evaluation


def test_a_literal_key_read_reads_the_stores_key() -> None:
    body = _function(PLACE_ITEM).substitute({}).body
    ((store, call),) = _item_stores(body)
    assert isinstance(store.evaluation, str)
    # The statement keeps its key expression: it evaluates it itself.
    key, _value = call.args
    assert key.kind == "Constant"
    ret = body[-1]
    assert isinstance(ret, Return)
    # ``box['a']`` reads the object ``box['a'] = 1`` left, through its key.
    _reads_after(ret.value, store)


def test_a_ground_name_key_read_reads_the_stores_key() -> None:
    body = _function(PLACE_ITEM_BY_NAME).substitute({}).body
    ((store, call),) = _item_stores(body)
    assert isinstance(store.evaluation, str)
    # The store's key is ``k``'s key reference, never a value built for it.
    key, _value = call.args
    assert key.kind == "EvaluationRef"
    assert not getattr(key, "place", False)
    assert ground_subscript_key(key) == "a"
    ret = body[-1]
    assert isinstance(ret, Return)
    # ``box['a']`` reads the object ``box[k] = 1`` left, through its key.
    _reads_after(ret.value, store)


def test_a_call_key_leaves_the_field_unknown_and_is_not_called_again() -> None:
    body = _function(PLACE_ITEM_BY_CALL).substitute({}).body
    (first, _first_call), (by_call, call) = _item_stores(body)
    # The store keeps its call as the key: the statement evaluates it, once,
    # at reduce; nothing was built for it at substitution.
    key, _value = call.args
    assert key.kind == "Call"
    ret = body[-1]
    assert isinstance(ret, Return)
    # ``g()`` may name ``'a'``: the read is not the first store's key; it
    # reads the object after the second store, through that statement's key,
    # and every post-state it holds reads its call's pair there: ``g()`` is
    # never called again.
    assert not (
        ret.value.kind == "EvaluationRef"
        and getattr(ret.value, "place", False)
        and ret.value.evaluation == first.evaluation
    )
    _reads_after(ret.value, by_call)


# ---------------------------------------------------------------------------
# 11. ``box[-1]`` and ``{k: ...}``: a negative int key and a dict display's
#     key are decided by the key expression's ground value too.
# ---------------------------------------------------------------------------


def test_a_negative_key_read_reads_the_stores_key() -> None:
    body = _function(PLACE_ITEM_NEGATIVE).substitute({}).body
    ((store, call),) = _item_stores(body)
    assert isinstance(store.evaluation, str)
    # The statement keeps its key expression: ``-1`` is a unary minus.
    key, _value = call.args
    assert key.kind == "UnaryOp"
    assert ground_subscript_key(key) == -1
    ret = body[-1]
    assert isinstance(ret, Return)
    # ``box[-1]`` reads the object ``box[-1] = 1`` left, through its key.
    _reads_after(ret.value, store)


def test_a_dict_display_key_is_decided_by_its_ground_value() -> None:
    body = _function(DICT_DISPLAY_BY_NAME).substitute({}).body
    ret = body[-1]
    assert isinstance(ret, Return)
    display = ret.value
    assert display.kind == "Dict"
    (key,) = display.keys
    # The key is ``k``'s key reference, never the literal put in its place.
    assert key.kind == "EvaluationRef"
    assert ground_subscript_key(key) == "a"
    (member,) = display.values
    assert _display_member(display, ("item", "a")) is member
    assert _display_member(display, ("item", "b")) is None


# ---------------------------------------------------------------------------
# 12. A chained store and an unpack's store leaf (#7757 item 7, found by
#     #8010): each store target is ``target = v``'s own statement, so a later
#     read of the object sees the store, as after a single-target store.
# ---------------------------------------------------------------------------

# A chained store on an object place.
CHAIN_FIELD = (
    "class C:\n"
    "    pass\n"
    "\n"
    "def f():\n"
    "    o = C()\n"
    "    a = o.x = 5\n"
    "    return o.x\n"
)
# A chained store on a decided local dict.
CHAIN_ITEM = "def f():\n    d = {}\n    a = d['k'] = 5\n    return d['k']\n"
# A chained store on a decided local list, the whole list read after it.
CHAIN_LIST = "def f():\n    xs = [0]\n    a = xs[0] = 9\n    return xs\n"
# An unpack's store leaf on an object place.
UNPACK_FIELD = (
    "class C:\n"
    "    pass\n"
    "\n"
    "def f():\n"
    "    o = C()\n"
    "    a, o.x = 1, 2\n"
    "    return o.x\n"
)


def test_a_chained_field_store_is_read_after_it(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, CHAIN_FIELD, "chain_field"))
    assert returned == [TermValue(5)], returned


def test_a_chained_item_store_is_read_after_it(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, CHAIN_ITEM, "chain_item"))
    assert returned == [TermValue(5)], returned


def test_a_chained_list_store_is_in_the_list_read_after_it(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, CHAIN_LIST, "chain_list"))
    assert returned == [fresh(ListValue, (TermValue(9),))], returned


def test_an_unpack_field_store_is_read_after_it(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, UNPACK_FIELD, "unpack_field"))
    assert returned == [TermValue(2)], returned


def test_a_chained_store_is_the_single_store_statement() -> None:
    """``a = o.x = 5``'s store target is ``o.x = <the chain's value>``'s own
    statement, built by the single-target ``Assign.substitute``: the
    post-state a later ``o.x`` reads holds that statement's key, never the
    state before the store."""
    body = _function(CHAIN_FIELD).substitute({}).body
    chain = next(
        node for node in body if isinstance(node, Assign) and len(node.targets) == 2
    )
    (store,) = chain.stores
    assert isinstance(store, ReceiverFieldStoreStatement)
    assert isinstance(store.evaluation, str)
    assert store.evaluation != chain.evaluation
    # The store reads the chain's one evaluation: it evaluates nothing again.
    assert store.value.kind == "EvaluationRef"
    assert store.value.evaluation == chain.evaluation
    ret = body[-1]
    assert isinstance(ret, Return)
    states = [
        node for node in ret.value.walk() if isinstance(node, ReceiverFieldStoreState)
    ]
    assert states
    for state in states:
        assert state.value.kind == "EvaluationRef"
        assert state.value.place is True
        assert state.value.evaluation == store.evaluation

    # Discrimination: the same store alone threads the same kind of state.
    single = _function(FIELD).substitute({}).body
    assert any(isinstance(node, ReceiverFieldStoreStatement) for node in single)


# ---------------------------------------------------------------------------
# 13. ``o[k]: int = v`` and ``o.f: int = v`` (#7757): an annotated store with
#     a value is the store ``o[k] = v`` / ``o.f = v`` -- the same statement,
#     through the one door each store target takes (the container-mutation
#     door for an item, the receiver field store for a field), decided by
#     value at reduce.  The annotation of such a target is never stored and,
#     in a function body, never evaluated.
# ---------------------------------------------------------------------------

# 2.'s item store, annotated.
SUBSCRIPT_ANNOTATED = (
    "def f():\n"
    "    d = {}\n"
    "    x = 1\n"
    "    d['k']: int = x\n"
    "    x += 1\n"
    "    return d['k']\n"
)
# 10.'s item store on an object place, annotated.
PLACE_ITEM_ANNOTATED = (
    "class Box:\n"
    "    pass\n"
    "\n"
    "def f():\n"
    "    box = Box()\n"
    "    box['a']: int = 1\n"
    "    return box['a']\n"
)
# 1.'s field store, annotated.
FIELD_ANNOTATED = (
    "class C:\n"
    "    pass\n"
    "\n"
    "def f():\n"
    "    o = C()\n"
    "    x = 1\n"
    "    o.x: int = x\n"
    "    x += 1\n"
    "    return o.x\n"
)


def _same_statements(annotated: str, plain: str) -> list:
    """The annotated function's substituted body, after asserting it is the
    plain one's statement for statement: the same kinds, no ``AnnAssign``
    left, the same sugar."""
    body = _function(annotated).substitute({}).body
    assert not any(isinstance(node, AnnAssign) for node in body)
    assert [node.kind for node in body] == [
        node.kind for node in _function(plain).substitute({}).body
    ]
    annotated_sugar = _function(annotated).sugar().statements
    plain_sugar = _function(plain).sugar().statements
    assert [type(sugar).__name__ for sugar in annotated_sugar] == [
        type(sugar).__name__ for sugar in plain_sugar
    ]
    return list(body)


def test_an_annotated_item_store_is_the_item_store(tmp_path: Path) -> None:
    body = _same_statements(SUBSCRIPT_ANNOTATED, SUBSCRIPT)
    ((store, _call),) = _item_stores(body)
    assert isinstance(store.evaluation, str)
    ret = body[-1]
    assert isinstance(ret, Return)
    _reads_after(ret.value, store)
    annotated = _returned(_outcome(tmp_path, SUBSCRIPT_ANNOTATED, "subscript_ann"))
    plain = _returned(_outcome(tmp_path, SUBSCRIPT, "subscript_plain"))
    assert annotated == plain == [ONE], (annotated, plain)


def test_an_annotated_item_store_on_an_object_place_takes_the_door() -> None:
    # The store the deleted object-place subscript arm took: the one
    # container-mutation door's statement, as ``box['a'] = 1`` is.
    body = _same_statements(PLACE_ITEM_ANNOTATED, PLACE_ITEM)
    ((store, call),) = _item_stores(body)
    assert isinstance(store.evaluation, str)
    key, _value = call.args
    assert key.kind == "Constant"
    ret = body[-1]
    assert isinstance(ret, Return)
    _reads_after(ret.value, store)


def test_an_annotated_field_store_is_the_field_store(tmp_path: Path) -> None:
    body = _same_statements(FIELD_ANNOTATED, FIELD)
    store = next(node for node in body if isinstance(node, ReceiverFieldStoreStatement))
    assert isinstance(store.evaluation, str)
    annotated = _returned(_outcome(tmp_path, FIELD_ANNOTATED, "field_ann"))
    plain = _returned(_outcome(tmp_path, FIELD, "field_plain"))
    assert annotated == plain == [ONE], (annotated, plain)
