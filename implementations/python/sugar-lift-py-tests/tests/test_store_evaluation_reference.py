"""A store and a call's object are read through their statement's key
(temporal choice 1, #7661; #7757 item 7, after #7958).

#7958 keyed every Name an assignment binds.  Three reads still evaluated
the right-hand side again where they were read:

1. ``o.x = v`` threaded ``v`` into later reads of the place: ``o.x`` on a
   coordinate receiver (``_ReceiverFieldProjection``) and every read of
   ``o`` after a receiver field store (``ReceiverFieldStoreState``).  The
   store now evaluates ``v`` once and binds it under its statement's key
   (``KeyedStoreSugar``); the read is a reference to that key (``place``).
2. ``d[k] = v`` on a decided dict rebound ``d`` to a projection of the
   mutating call, which reduced the call (and ``v``) again at every read.
   The statement binds the call's pair under its key
   (``ContainerMutationStatementSugar``); the projection reads it there.
3. A call's result kept as its object identity (``OpaqueObjectStateV1``,
   ``Assign.refine_binding_entries``) reduced its call again at every read.
   It reads the assignment's key, as the name's reference does.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset
from sugar_lift_py_tests.sugar.assign_sugar import KeyedStoreSugar
from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
    ContainerMutationStatementSugar,
)
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
    ReceiverFieldStoreSugar,
)
from sugar_lift_py_tests.temporal.temporal_context import projection_key
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.nodes import (
    AnnAssign,
    Assign,
    BuiltinContainerProjection,
    ContainerMutationStatement,
    FunctionDef,
    OpaqueObjectStateV1,
    ReceiverFieldStoreState,
    ReceiverFieldStoreStatement,
    Return,
)
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

    for exit_ in outcome_to_exitset(outcome).exits:
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
    stored = store.store.value.value
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
    annotated = next(node for node in body if isinstance(node, AnnAssign))
    assert isinstance(annotated.evaluation, str)
    # ``self.y = self.x``: its right-hand side reads what ``self.x: int = x``
    # stored, through that statement's key, never ``x`` (rebound since).
    read = body[-1].value
    assert read.kind == "EvaluationRef"
    assert read.place is True
    assert read.evaluation == annotated.evaluation


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
    body = _function(SUBSCRIPT).substitute({}).body
    mutation = next(
        node for node in body if isinstance(node, ContainerMutationStatement)
    )
    assert isinstance(mutation.evaluation, str)
    ret = body[-1]
    assert isinstance(ret, Return)
    projections = [
        node
        for node in ret.value.walk()
        if isinstance(node, BuiltinContainerProjection)
    ]
    assert projections
    for projection in projections:
        assert projection.evaluation == mutation.evaluation
        pair = projection.sugar().call
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
    body = _function(CALL_READ_TWICE).substitute({}).body
    assign = next(node for node in body if isinstance(node, Assign))
    key = projection_key(assign.evaluation, "r")
    ret = body[-1]
    assert isinstance(ret, Return)
    reads = ret.value.elts
    assert len(reads) == 2
    for read in reads:
        assert isinstance(read, OpaqueObjectStateV1)
        assert read.evaluation == key
        assert read.base.kind == "Call"
        sugar = read.sugar()
        # The key, not a second term for the call.
        assert isinstance(sugar, EvaluationRefSugar)
        assert sugar.evaluation == key
