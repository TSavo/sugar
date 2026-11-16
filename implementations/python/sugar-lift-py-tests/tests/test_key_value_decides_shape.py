"""A key's ground value decides a shape; the read is still the key (#7757
item 7, after #7958).

#7958 bound every assigned name to its own statement's key, so substitution
no longer saw a display or constant through a name: ``xs = [1, 2]; for x in
xs`` and ``n = 3; for i in range(n)`` stopped unrolling, a local constant
stopped deciding a branch at substitution, and a starred unpack of a name
gave its targets nothing to decide with.  The key reference carries the
right-hand side it was given (``of``); where that is ground, substitution asks
the reference for it (``EvaluationRef.ground_value``) and uses it only to
decide the shape.

Since #8957 (#7757 new 6) a loop has one mechanism: no rewrite unrolls it.
``For.substitute`` keeps the loop as its one recurrence statement
(``LoopRecurrenceStatement``), and the reduction runs its items one by one
where it holds the iterable's members (``LoopRecurrenceSugar``,
``iterator_operation.in_hand_iterable``): a key whose value is a display or a
ground ``range``.  So the key's value decides how many items run at reduce,
and each item reads the value the key holds there.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.temporal.temporal_context import projection_key
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.nodes import Assign, EvaluationRef, FunctionDef, Return
from sugar_source_tree.tree import SourceFile

TWO, THREE = TermValue(2), TermValue(3)


def _function(source: str, name: str = "f") -> FunctionDef:
    tree = SourceFile(
        (source, "key_value_decides_shape.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )


def _body(source: str) -> tuple:
    return _function(source).substitute({}).body


def _stores(body, name: str) -> list:
    """The keyed stores of ``name`` the body holds at its own level."""
    return [
        node
        for node in body
        if isinstance(node, Assign)
        and len(node.targets) == 1
        and getattr(node.targets[0], "id", None) == name
        and isinstance(getattr(node, "evaluation", None), str)
    ]


def _kinds(body) -> set:
    return {node.kind for node in body}


def _one_loop(body) -> None:
    """The loop stays one statement after the rewrite: its recurrence, never
    its items (#8957)."""
    kinds = [node.kind for node in body]
    assert kinds.count("LoopRecurrenceStatement") == 1, kinds
    assert "For" not in kinds, kinds


def _outcome(tmp_path: Path, source: str, stem: str, name: str = "f"):
    """``name``'s outcome, its source read through the workspace-relative
    lift door: a loop whose items the reduction runs in hand states the
    exits of its ``iter``/``next`` operations (``LoopRecurrenceSugar``) as
    ground exits, which cite a workspace-relative locus (``ground_exit``)."""
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    functions = SourceFile(
        workspace_path_source(str(path), root=str(tmp_path)),
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
        # A function's completed value is its ``UniverseValue``; what the
        # body returned is in the record it carries.
        record = getattr(value, "record", None)
        if record is not None:
            visit(record)

    assert isinstance(outcome, ExitSet), outcome
    for exit_ in outcome.exits:
        if isinstance(exit_, Completed):
            visit(exit_.value)
    return found


# ---------------------------------------------------------------------------
# A loop over a name whose key holds a display unrolls; each item reads the key.
# ---------------------------------------------------------------------------

LIST_LOOP = (
    "def f():\n"
    "    xs = [1, 2]\n"
    "    for x in xs:\n"
    "        r = x\n"
    "    return r\n"
)


def test_a_loop_over_a_keyed_display_stays_one_loop_at_rewrite() -> None:
    # The rewrite never decides the iterable: no item is a store of ``x`` at
    # the body's level.  The reduction runs the items (below).
    body = _body(LIST_LOOP)
    _one_loop(body)
    assert _stores(body, "x") == []


def test_each_unrolled_item_reads_the_key_not_the_member() -> None:
    body = _body(LIST_LOOP)
    (xs,) = _stores(body, "xs")
    key = projection_key(xs.evaluation, "xs")
    for index, store in enumerate(_stores(body, "x")):
        item = store.value
        assert item.kind == "Subscript"
        assert isinstance(item.value, EvaluationRef)
        assert item.value.evaluation == key
        assert item.slice_.value == index


def test_a_loop_over_a_keyed_display_returns_its_last_item(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, LIST_LOOP, "list_loop"))
    assert returned == [TWO], returned


RANGE_LOOP = (
    "def f():\n"
    "    n = 3\n"
    "    for i in range(n):\n"
    "        r = i\n"
    "    return r\n"
)


def test_a_range_over_a_keyed_int_stays_one_loop_at_rewrite() -> None:
    body = _body(RANGE_LOOP)
    _one_loop(body)
    assert _stores(body, "i") == []


def test_a_range_over_a_keyed_int_runs_its_items_at_reduce(tmp_path: Path) -> None:
    # ``range(n)`` over the key's ground 3 is the ints it yields
    # (``in_hand_iterable``): three items, the last binds ``r`` to 2.
    returned = _returned(_outcome(tmp_path, RANGE_LOOP, "range_loop"))
    assert returned == [TWO], returned


# ---------------------------------------------------------------------------
# The latest key decides.
# ---------------------------------------------------------------------------


def test_a_rebound_name_decides_by_its_latest_key(tmp_path: Path) -> None:
    # ``range(n)`` reads the second key, 4: the last item binds ``r`` to 3.
    returned = _returned(
        _outcome(
            tmp_path,
            "def f():\n"
            "    n = 3\n"
            "    n = 4\n"
            "    for i in range(n):\n"
            "        r = i\n"
            "    return r\n",
            "rebound_range",
        )
    )
    assert returned == [THREE], returned


def test_an_augmented_rebind_is_not_read_through_the_old_value() -> None:
    # ``n += 1`` binds ``n`` to its own key, which carries no ground value:
    # the loop is not unrolled by the 3 the earlier key held.
    body = _body(
        "def f():\n"
        "    n = 3\n"
        "    n += 1\n"
        "    r = 0\n"
        "    for i in range(n):\n"
        "        r = i\n"
        "    return r\n"
    )
    assert len(_stores(body, "i")) != 3
    assert len(_stores(body, "i")) == 0


# ---------------------------------------------------------------------------
# A local constant decides a branch at substitution.
# ---------------------------------------------------------------------------


def test_the_key_answers_its_ground_value() -> None:
    body = _body("def f():\n    DEBUG = False\n    return DEBUG\n")
    ret = body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    ground = ret.value.ground_value()
    assert ground is not None
    assert ground.kind == "Constant"
    assert ground.value is False


def test_a_local_constant_decides_a_jumping_if_at_reduce(tmp_path: Path) -> None:
    # ``DEBUG``'s key holds False: no item takes the ``break``, and the last
    # item binds ``r`` to 2.  The loop stays one statement at the rewrite.
    source = (
        "def f():\n"
        "    DEBUG = False\n"
        "    r = 0\n"
        "    for i in [1, 2]:\n"
        "        if DEBUG:\n"
        "            break\n"
        "        r = i\n"
        "    return r\n"
    )
    _one_loop(_body(source))
    returned = _returned(_outcome(tmp_path, source, "jumping_if"))
    assert returned == [TWO], returned


def test_a_local_constant_decides_a_while() -> None:
    body = _body(
        "def f():\n"
        "    DEBUG = False\n"
        "    r = 1\n"
        "    while DEBUG:\n"
        "        r = 2\n"
        "    return r\n"
    )
    assert "While" not in _kinds(body)
    assert len(_stores(body, "r")) == 1


# ---------------------------------------------------------------------------
# A starred unpack.
# ---------------------------------------------------------------------------


def test_a_starred_unpack_of_a_display_unpacks() -> None:
    body = _body("def f():\n    a, *b = [1, 2, 3]\n    return b\n")
    ret = body[-1]
    assert isinstance(ret.value, EvaluationRef)
    ground = ret.value.ground_value()
    assert ground is not None
    assert ground.kind == "List"
    assert [element.value for element in ground.elts] == [2, 3]


def test_a_starred_unpack_of_a_keyed_display_decides_later_shapes(
    tmp_path: Path,
) -> None:
    # ``b`` is the list ``[2, 3]`` the unpack made: two items, the last binds
    # ``r`` to 3.
    source = (
        "def f():\n"
        "    xs = [1, 2, 3]\n"
        "    a, *b = xs\n"
        "    for y in b:\n"
        "        r = y\n"
        "    return r\n"
    )
    _one_loop(_body(source))
    returned = _returned(_outcome(tmp_path, source, "starred_unpack"))
    assert returned == [THREE], returned


# ---------------------------------------------------------------------------
# A list the body can reach is not unrolled through its key.
# ---------------------------------------------------------------------------


def test_a_list_the_body_reads_is_not_unrolled() -> None:
    body = _body(
        "def f():\n"
        "    xs = [1, 2]\n"
        "    for x in xs:\n"
        "        ys = xs\n"
        "    return 0\n"
    )
    assert _stores(body, "x") == []


def test_a_tuple_the_body_reads_stays_one_loop_at_rewrite() -> None:
    # Whether the items run in hand is the reduction's decision (a tuple's
    # contents are current: ``object_identity.contents_stale``), never the
    # rewrite's.
    body = _body(
        "def f():\n"
        "    xs = (1, 2)\n"
        "    for x in xs:\n"
        "        ys = xs\n"
        "    return 0\n"
    )
    _one_loop(body)
    assert _stores(body, "x") == []


# ---------------------------------------------------------------------------
# A list that escaped before the loop is not unrolled when the body runs code
# that could reach it (#7757 item 7, the gap #7973 left).
# ---------------------------------------------------------------------------


def _escaped(escape: str, call: str, *, display: str = "[1, 2]") -> str:
    return (
        "def f(box, d, register):\n"
        f"    xs = {display}\n"
        f"{escape}"
        "    for x in xs:\n"
        f"        {call}\n"
        "        r = x\n"
        "    return 0\n"
    )


def test_a_list_stored_on_an_object_is_not_unrolled() -> None:
    body = _body(_escaped("    box.items = xs\n", "box.grow()"))
    assert _stores(body, "x") == []


def test_a_list_stored_in_a_container_is_not_unrolled() -> None:
    body = _body(_escaped("    d['k'] = xs\n", "d['k'].append(3)"))
    assert _stores(body, "x") == []


def test_a_list_passed_to_a_call_is_not_unrolled() -> None:
    body = _body(_escaped("    register(xs)\n", "box.grow()"))
    assert _stores(body, "x") == []


def test_a_list_a_nested_def_captures_is_not_unrolled() -> None:
    body = _body(
        _escaped("    def grow():\n        xs.append(3)\n", "grow()")
    )
    assert _stores(body, "x") == []


def test_a_list_a_lambda_captures_is_not_unrolled() -> None:
    body = _body(_escaped("    grow = lambda: xs.append(3)\n", "grow()"))
    assert _stores(body, "x") == []


def test_a_list_an_alias_lets_escape_is_not_unrolled() -> None:
    body = _body(_escaped("    ys = xs\n    box.items = ys\n", "box.grow()"))
    assert _stores(body, "x") == []


def test_a_list_stored_in_a_display_is_not_unrolled() -> None:
    body = _body(_escaped("    box.held = [xs]\n", "box.grow()"))
    assert _stores(body, "x") == []


def test_an_escaped_tuple_stays_one_loop_at_rewrite() -> None:
    body = _body(
        _escaped("    box.items = xs\n", "box.grow()", display="(1, 2)")
    )
    _one_loop(body)
    assert _stores(body, "x") == []


def test_a_list_stored_on_a_formal_is_not_unrolled_even_with_a_pure_body() -> None:
    # ``box.items = xs`` is ``type(box).__setattr__(box, 'items', xs)``; the
    # formal's class is not decided, so the store may run code handed ``xs``
    # (``class B: def __setattr__(s, k, v): v.append(3)`` makes the loop run
    # three times).  The list's contents after the store are not decided, so
    # the loop over it is never unrolled to the two items the display held,
    # however pure the body is.
    body = _body(_escaped("    box.items = xs\n", "r = x + 1"))
    assert _stores(body, "x") == []


def test_a_local_list_whose_body_calls_stays_one_loop_at_rewrite() -> None:
    body = _body(_escaped("", "box.grow()"))
    _one_loop(body)
    assert _stores(body, "x") == []


# ---------------------------------------------------------------------------
# A hidden call runs code too: an operator or attribute read on a source
# object dispatches its class's dunder or property (#7757 item 7, the gap
# #7980 named).
# ---------------------------------------------------------------------------


def _hidden(statement: str) -> str:
    return (
        "class C:\n"
        "    def __init__(self, box):\n"
        "        self.box = box\n"
        "    def __add__(self, other):\n"
        "        self.box.items.append(3)\n"
        "        return other\n"
        "    @property\n"
        "    def size(self):\n"
        "        self.box.items.append(3)\n"
        "        return 0\n"
        "\n"
        "def f(box, obj: C):\n"
        "    xs = [1, 2]\n"
        "    box.items = xs\n"
        "    for x in xs:\n"
        f"        {statement}\n"
        "        r = x\n"
        "    return 0\n"
    )


def test_an_escaped_list_whose_body_adds_to_a_source_object_is_not_unrolled() -> None:
    body = _body(_hidden("y = obj + 1"))
    assert _stores(body, "x") == []


def test_an_escaped_list_whose_body_adds_constants_is_still_not_unrolled() -> None:
    # The body runs no code, but the escape itself may have: ``box`` is a
    # formal, so ``box.items = xs`` may run a ``__setattr__`` handed ``xs``
    # (see ``test_a_list_stored_on_a_formal_is_not_unrolled_even_with_a_pure_body``).
    body = _body(_hidden("y = 1 + 2"))
    assert _stores(body, "x") == []


def test_an_escaped_list_whose_body_reads_a_property_is_not_unrolled() -> None:
    body = _body(_hidden("y = obj.size"))
    assert _stores(body, "x") == []
