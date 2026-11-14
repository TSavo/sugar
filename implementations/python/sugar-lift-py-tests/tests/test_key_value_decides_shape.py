"""A key's ground value decides a shape; the read is still the key (#7757
item 7, after #7958).

#7958 bound every assigned name to its own statement's key, so substitution
no longer saw a display or constant through a name: ``xs = [1, 2]; for x in
xs`` and ``n = 3; for i in range(n)`` stopped unrolling, a local constant
stopped deciding a branch at substitution, and a starred unpack of a name
gave its targets nothing to decide with.  The key reference carries the
right-hand side it was given (``of``); where that is ground, substitution asks
the reference for it (``EvaluationRef.ground_value``) and uses it only to
decide the shape.  Each unrolled item reads the key (``xs[i]``), never the
display's member.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset
from sugar_lift_py_tests.temporal.temporal_context import projection_key
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.nodes import Assign, EvaluationRef, FunctionDef, Return
from sugar_source_tree.tree import SourceFile

TWO = TermValue(2)


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

    for exit_ in outcome_to_exitset(outcome).exits:
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


def test_a_loop_over_a_keyed_display_unrolls() -> None:
    body = _body(LIST_LOOP)
    assert "For" not in _kinds(body)
    assert len(_stores(body, "x")) == 2


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


def test_a_range_over_a_keyed_int_unrolls() -> None:
    body = _body(
        "def f():\n"
        "    n = 3\n"
        "    for i in range(n):\n"
        "        r = i\n"
        "    return r\n"
    )
    assert "For" not in _kinds(body)
    assert len(_stores(body, "i")) == 3


# ---------------------------------------------------------------------------
# The latest key decides.
# ---------------------------------------------------------------------------


def test_a_rebound_name_decides_by_its_latest_key() -> None:
    body = _body(
        "def f():\n"
        "    n = 3\n"
        "    n = 4\n"
        "    for i in range(n):\n"
        "        r = i\n"
        "    return r\n"
    )
    assert len(_stores(body, "i")) == 4


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


def test_a_local_constant_prunes_a_jumping_if() -> None:
    body = _body(
        "def f():\n"
        "    DEBUG = False\n"
        "    r = 0\n"
        "    for i in [1, 2]:\n"
        "        if DEBUG:\n"
        "            break\n"
        "        r = i\n"
        "    return r\n"
    )
    kinds = _kinds(body)
    assert "For" not in kinds
    assert "If" not in kinds
    assert len(_stores(body, "i")) == 2


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


def test_a_starred_unpack_of_a_keyed_display_decides_later_shapes() -> None:
    body = _body(
        "def f():\n"
        "    xs = [1, 2, 3]\n"
        "    a, *b = xs\n"
        "    for y in b:\n"
        "        r = y\n"
        "    return r\n"
    )
    assert "For" not in _kinds(body)
    assert len(_stores(body, "y")) == 2


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


def test_a_tuple_the_body_reads_is_unrolled() -> None:
    body = _body(
        "def f():\n"
        "    xs = (1, 2)\n"
        "    for x in xs:\n"
        "        ys = xs\n"
        "    return 0\n"
    )
    assert len(_stores(body, "x")) == 2


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


def test_an_escaped_tuple_is_unrolled() -> None:
    body = _body(
        _escaped("    box.items = xs\n", "box.grow()", display="(1, 2)")
    )
    assert len(_stores(body, "x")) == 2


def test_an_escaped_list_with_a_pure_body_is_unrolled() -> None:
    body = _body(_escaped("    box.items = xs\n", "r = x + 1"))
    assert len(_stores(body, "x")) == 2


def test_a_local_list_whose_body_calls_is_unrolled() -> None:
    # Nothing but ``xs`` holds the list: a call in the body cannot reach it.
    body = _body(_escaped("", "box.grow()"))
    assert len(_stores(body, "x")) == 2
