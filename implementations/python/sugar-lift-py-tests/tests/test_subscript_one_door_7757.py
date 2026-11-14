"""Every subscript read goes through the one door (#7757).

``discharge_subscript`` is the one door for ``receiver[index]``: a parameter
in either operand defers to the caller (``defer_formal_subscript``), else the
receiver answers.  A pattern's read, a walrus's read, a mapping object's
``__getitem__``, an opaque operation's downstream read and an append's
residual read all take it, and no module outside the door calls a floor's
``subscript`` / ``subscript_with`` on another value (the law below).

A parameter in a slice bound (``(0, 1, 2)[start:]``) defers the slice itself
(``construct_slice``, the ``slice`` carrier): the caller's actual decides the
slice, and the read continues on it.

No floor operation is dispatched by its name either (the second law): a
guarded value reads each arm through the door, never as
``getattr(arm, "subscript")``, so a parameter arm defers its read too.
"""

from __future__ import annotations

import ast
from pathlib import Path

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import (
    DictValue,
    ListValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, make_var
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef, Subscript
from sugar_source_tree.tree import SourceFile, SourceTree


def _tree(source: str, name: str) -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _site():
    source = "def helper(xs, key):\n    return xs[key]\n"
    tree = _tree(source, "one-door-helper.py")
    return next(node for node in tree.nodes() if isinstance(node, Subscript)).fragment


def _formal(site, name: str = "key", ordinal: int = 1):
    """A parameter's symbolic stand-in, its coordinate minted at ``site``."""
    span = site.line_col_span
    owner = SourceFragmentCoordinateV1(
        site.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    coordinate = FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=site.source_cid,
        owner_definition_locus=owner,
        declaration_locus=owner,
        ordinal=ordinal,
        parameter_kind="positional-or-keyword",
        declared_name=name,
        sort=PrimitiveSort("Value"),
    )
    return SymbolicValue(make_var(name), coordinate), coordinate


def _assert_index_deferred(pending, coordinate) -> None:
    assert isinstance(pending, NativeOperationExitCarrierV1), type(pending)
    assert pending.demand.operator == "subscript"
    assert pending.demand.operand_coordinate_cids == (None, coordinate.coordinate_cid)


# ---------------------------------------------------------------------------
# The law: no module outside the door reads another value's subscript
# ---------------------------------------------------------------------------

_DOOR = "operations/subscript_operation.py"
_READS = frozenset({"subscript", "subscript_with", "subscript_with_occurrence"})


def _own(receiver) -> bool:
    """``self`` / ``super()``: a floor answering its own subscript."""
    if isinstance(receiver, ast.Name):
        return receiver.id == "self"
    return (
        isinstance(receiver, ast.Call)
        and isinstance(receiver.func, ast.Name)
        and receiver.func.id == "super"
    )


def _bypasses_in(source: str, relative: str) -> list[str]:
    """Each call of a floor's subscript protocol that skips the door: any call
    on another value, and a floor's call on itself outside its own subscript
    protocol methods (``self.subscript`` from ``call_method_value`` skipped the
    door before #7757)."""
    tree = ast.parse(source, filename=relative)
    allowed: set[int] = set()
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if function.name not in _READS:
            continue
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _READS
                and _own(node.func.value)
            ):
                allowed.add(id(node))
    return [
        f"{relative}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _READS
        and id(node) not in allowed
    ]


def test_no_module_outside_the_door_reads_a_floors_subscript() -> None:
    import sugar_lift_py_tests

    root = Path(sugar_lift_py_tests.__file__).resolve().parent
    found = []
    for path in SourceTree(root).paths():
        relative = path.relative_to(root).as_posix()
        if relative == _DOOR:
            continue
        found.extend(_bypasses_in(path.read_text(encoding="utf-8"), relative))

    assert found == [], (
        "read through discharge_subscript (operations/subscript_operation.py), "
        f"never a floor's subscript protocol directly: {found}"
    )


def test_the_law_bites_on_a_read_that_skips_the_door() -> None:
    lying = (
        "class Wrapper:\n"
        "    def subscript(self, index, site):\n"
        "        return self.inner.subscript(index, site)\n"
        "\n"
        "    def call_method_value(self, name, arguments, *, owner, blame):\n"
        "        return self.subscript(arguments[0], blame)\n"
        "\n"
        "\n"
        "def read(value, index, site):\n"
        "    return value.subscript_with(index, site)\n"
    )
    truthful = (
        "class Floor:\n"
        "    def subscript_with(self, operation, ctx):\n"
        "        return self.subscript(operation.index, operation.blame)\n"
        "\n"
        "    def subscript(self, index, site):\n"
        "        return super().subscript(index, site)\n"
    )

    assert _bypasses_in(lying, "lying.py") == [
        "lying.py:3",
        "lying.py:6",
        "lying.py:10",
    ]
    assert _bypasses_in(truthful, "truthful.py") == []


# ---------------------------------------------------------------------------
# The law: no floor operation is dispatched by its name
# ---------------------------------------------------------------------------
#
# A read handed to each arm as ``_map("subscript", ...)`` and answered by
# ``getattr(arm, method)(...)`` never names ``.subscript`` / the door in source,
# so the law above cannot see it (#8109).  Every operation is called explicitly
# instead, through its one door.  This law refuses the three spellings of a call
# looked up by a name: ``getattr(value, name)(...)`` with a name that is not
# written out, a name bound to such a lookup and called in the same scope, and
# ``operator.methodcaller``.

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _looked_up_by_name(node) -> bool:
    """``getattr(value, name, ...)`` whose ``name`` is not written out."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and not (
            isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        )
    )


def _in_scope(scope):
    """Every node of ``scope`` outside the scopes nested in it."""
    pending = list(ast.iter_child_nodes(scope))
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, _SCOPES):
            pending.extend(ast.iter_child_nodes(node))


def _dispatches_by_name_in(source: str, relative: str) -> list[str]:
    tree = ast.parse(source, filename=relative)
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _looked_up_by_name(node.func):
            found.add(node.lineno)
        callee = node.func
        named = callee.id if isinstance(callee, ast.Name) else None
        attribute = callee.attr if isinstance(callee, ast.Attribute) else None
        if "methodcaller" in (named, attribute):
            found.add(node.lineno)
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    scopes = [tree, *(node for node in ast.walk(tree) if isinstance(node, functions))]
    for scope in scopes:
        nodes = list(_in_scope(scope))
        bound = {
            target.id
            for node in nodes
            if isinstance(node, ast.Assign) and _looked_up_by_name(node.value)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        found.update(
            node.lineno
            for node in nodes
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in bound
        )
    return [f"{relative}:{line}" for line in sorted(found)]


def test_no_module_dispatches_a_floor_operation_by_name() -> None:
    import sugar_lift_py_tests

    root = Path(sugar_lift_py_tests.__file__).resolve().parent
    found = []
    for path in SourceTree(root).paths():
        relative = path.relative_to(root).as_posix()
        found.extend(_dispatches_by_name_in(path.read_text(encoding="utf-8"), relative))

    assert found == [], (
        "call each floor operation explicitly, through its one door "
        f"(discharge_subscript, project_attribute, ...), never by name: {found}"
    )


def test_the_law_bites_on_a_call_looked_up_by_name() -> None:
    lying = (
        "from operator import methodcaller\n"
        "\n"
        "\n"
        "def distribute(arms, method, *args):\n"
        "    return [getattr(arm, method)(*args) for arm in arms]\n"
        "\n"
        "\n"
        "def dig(dug, name, other):\n"
        "    method = getattr(dug, name, None)\n"
        "    if callable(method):\n"
        "        return method(other)\n"
        "    return getattr(super(), name)(other)\n"
        "\n"
        "\n"
        "def each(arms):\n"
        "    return list(map(methodcaller('subscript', 0), arms))\n"
    )
    truthful = (
        "def probe(face, faces, name, site):\n"
        "    narrowed = getattr(face, 'stands_on_append_floor', None)\n"
        "    fields = tuple(getattr(other, name) for other in faces)\n"
        "    length = face.length(site)\n"
        "    return narrowed() if callable(narrowed) else (fields, length)\n"
    )

    assert _dispatches_by_name_in(lying, "lying.py") == [
        "lying.py:5",
        "lying.py:11",
        "lying.py:12",
        "lying.py:16",
    ]
    assert _dispatches_by_name_in(truthful, "truthful.py") == []


# ---------------------------------------------------------------------------
# A parameter index defers to the caller wherever the read is made
# ---------------------------------------------------------------------------


def test_a_match_mapping_read_with_a_parameter_key_defers_to_the_caller() -> None:
    from sugar_lift_py_tests.sugar.match_sugar import _read

    site = _site()
    key, coordinate = _formal(site)
    subject = DictValue(((StringValue("a"), TermValue(1)),))

    pending = _read(subject, key, site, None)

    _assert_index_deferred(pending, coordinate)
    exits = pending.discharge(None, {coordinate.coordinate_cid: StringValue("a")})
    assert exits.completed_value() == TermValue(1)


def test_a_match_projection_composes_a_deferred_read() -> None:
    """A pattern's read that waits on its caller (the carrier) enrolls the
    pattern's next step, run on the item the caller's actual selects."""
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.match_sugar import _each, _read

    site = _site()
    key, coordinate = _formal(site)
    subject = DictValue(((StringValue("a"), TermValue(1)),))

    pending = _each(
        _read(subject, key, site, None),
        lambda item: ExitSet.completed(("item", item)),
    )

    assert isinstance(pending, NativeOperationExitCarrierV1), type(pending)
    exits = pending.discharge(None, {coordinate.coordinate_cid: StringValue("a")})
    assert exits.completed_value() == ("item", TermValue(1))


def test_a_walrus_read_with_a_parameter_index_defers_to_the_caller() -> None:
    from sugar_lift_py_tests.floor.named_expression_value import (
        NamedExpressionValue,
    )

    site = _site()
    index, coordinate = _formal(site)
    walrus = NamedExpressionValue("ys", ListValue((TermValue(1), TermValue(2))))

    pending = walrus.subscript(index, site)

    _assert_index_deferred(pending, coordinate)
    exits = pending.discharge(None, {coordinate.coordinate_cid: TermValue(1)})
    read = exits.completed_value()
    assert isinstance(read, NamedExpressionValue), type(read)
    assert read.name == "ys"
    assert read.presented_value == TermValue(2)


def test_a_mapping_object_getitem_with_a_parameter_key_defers_to_the_caller() -> None:
    from sugar_lift_py_tests.floor.mapping_object_value import MappingObjectValue

    site = _site()
    key, coordinate = _formal(site)
    mapping = MappingObjectValue(
        "Registry", (), entries=((StringValue("a"), TermValue(1)),)
    )

    for pending in (
        mapping.subscript(key, site),
        mapping.call_method_value(
            "__getitem__", (key,), owner="test", blame=site, ctx=None
        ),
    ):
        _assert_index_deferred(pending, coordinate)
        exits = pending.discharge(None, {coordinate.coordinate_cid: StringValue("a")})
        assert exits.completed_value() == TermValue(1)


def test_a_guarded_parameter_arm_defers_its_read_through_the_door() -> None:
    """``(xs if c else (5,))[0]``: each arm is read through the one door, so
    the parameter arm's read waits on its caller and resolves with the
    caller's actual, beside the other arm's read under its own polarity."""
    from sugar_lift_py_tests.floor import GuardedValue
    from sugar_lift_py_tests.ir import atomic, not_
    from sugar_lift_py_tests.operations.subscript_operation import (
        discharge_subscript,
    )
    from sugar_lift_py_tests.outcome import Completed

    site = _site()
    receiver, coordinate = _formal(site, "xs", 0)
    guard = atomic("chosen", [])
    guarded = GuardedValue(guard, receiver, _tuple(5))

    pending = discharge_subscript(
        guarded, TermValue(0), site, None, owner="SubscriptSugar"
    )

    assert isinstance(pending, NativeOperationExitCarrierV1), type(pending)
    assert pending.demand.operator == "subscript"
    assert pending.demand.operand_coordinate_cids == (coordinate.coordinate_cid, None)
    exits = pending.discharge(None, {coordinate.coordinate_cid: _tuple(7)})
    assert all(isinstance(face, Completed) for face in exits.exits), exits
    assert {(face.guard, face.value) for face in exits.exits} == {
        (guard, TermValue(7)),
        (not_(guard), TermValue(5)),
    }


# ---------------------------------------------------------------------------
# A parameter in a slice bound: the slice defers, the read continues on it
# ---------------------------------------------------------------------------


def _tuple(*values: int) -> TupleValue:
    return TupleValue(tuple(TermValue(value) for value in values))


def test_a_parameter_slice_bound_defers_the_slice_to_the_caller() -> None:
    from sugar_lift_py_tests.floor.slice_value import construct_slice

    site = _site()
    start, coordinate = _formal(site, "start", 0)

    pending = construct_slice(start, None, None, site)

    assert isinstance(pending, NativeOperationExitCarrierV1), type(pending)
    assert pending.demand.operator == "slice"
    assert pending.demand.operand_coordinate_cids == (
        coordinate.coordinate_cid,
        None,
        None,
    )


def test_a_slice_with_no_parameter_bound_completes_here() -> None:
    from sugar_lift_py_tests.floor.slice_value import SliceValue, construct_slice

    outcome = construct_slice(TermValue(1), None, None, _site())

    assert outcome.completed_value() == SliceValue(TermValue(1), None, None)


def test_a_parameter_slice_read_with_actual_one_is_the_tail() -> None:
    """``(0, 1, 2)[start:]`` with ``start`` 1 is ``(1, 2)``."""
    from sugar_lift_py_tests.floor.slice_value import construct_slice
    from sugar_lift_py_tests.operations.subscript_operation import (
        discharge_subscript,
    )

    site = _site()
    start, coordinate = _formal(site, "start", 0)

    pending = construct_slice(start, None, None, site).and_then(
        lambda index: discharge_subscript(
            _tuple(0, 1, 2), index, site, None, owner="SubscriptSugar"
        )
    )
    exits = pending.discharge(None, {coordinate.coordinate_cid: TermValue(1)})

    assert exits.completed_value() == _tuple(1, 2)


def test_a_source_parameter_slice_bound_reaches_the_slice_carrier() -> None:
    source = "def tail(start):\n    return (0, 1, 2)[start:]\n"
    tree = _tree(source, "parameter-slice-helper.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    (coordinate,) = function.sugar().formal_coordinates

    outcome = function.sugar().desugar(None)

    assert isinstance(outcome, NativeOperationExitCarrierV1), type(outcome)
    assert outcome.demand.operator == "slice"
    assert outcome.demand.operand_coordinate_cids == (
        coordinate.coordinate_cid,
        None,
        None,
    )
