"""Every subscript read goes through the one door (#7757).

``discharge_subscript`` is the one door for ``receiver[index]``: the
receiver answers, and nothing waits on a caller's actual (audit 2 row NEW-1).
A parameter receiver is the one undecided read; a parameter index on a
receiver the lift decides is that receiver's own read with the symbolic key.
A pattern's read, a walrus's read, an
opaque operation's downstream read and an append's residual read all take
it, and no module outside the door calls a floor's ``subscript`` /
``subscript_with`` on another value (the law below).

A parameter in a slice bound (``(0, 1, 2)[start:]``) stands in the slice as
its symbolic value (``construct_slice`` never raises, as ``BUILD_SLICE``
does not), and the slice's reader reads it.

No floor operation is dispatched by its name either (the second law): a
guarded value reads each arm through the door, never as
``getattr(arm, "subscript")``, so a parameter arm is read as it is unguarded.
"""

from __future__ import annotations

import ast
from pathlib import Path

from frame_fresh import fresh
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
    # In source order: ``ast.walk`` is breadth-first, so a call in a module
    # function would otherwise be named before the calls in a class's methods
    # above it.
    bypasses = sorted(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _READS
            and id(node) not in allowed
        ),
        key=lambda node: (node.lineno, node.col_offset),
    )
    return [f"{relative}:{node.lineno}" for node in bypasses]


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
# A parameter index is read wherever the read is made; nothing waits on a
# caller's actual (#7757, audit 2 row NEW-1)
# ---------------------------------------------------------------------------


def _assert_undecided_read(exits, site, *, completed: int = 1) -> None:
    """The one undecided read (``FloorValue.undecided_subscript``), no
    carrier: a face completing under its own atom and an
    ``UndeterminedRaiseEffect`` halt, both owing the read's ``undecided``
    member (reason ``unanswered``) at ``site``.  ``completed`` counts the
    completed faces (a guarded receiver's decided arm adds its own)."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
    from sugar_lift_py_tests.unanswered_calls import unanswered_call

    done = [arm for arm in exits.exits if isinstance(arm, Completed)]
    (halt,) = [arm for arm in exits.exits if isinstance(arm, Halted)]
    assert len(done) == completed, exits
    assert isinstance(halt.effect, UndeterminedRaiseEffect), halt.effect
    assert unanswered_call(None, site) in halt.owed


def test_a_match_mapping_read_with_a_parameter_key_is_the_undecided_read() -> None:
    """``{'a': 1}`` read at a parameter key: the dict's own read, whose key's
    hash and equality nothing here decides -- the undecided read, its halt
    kept, never a carrier waiting on the caller."""
    from sugar_lift_py_tests.sugar.match_sugar import _read

    site = _site()
    key, _coordinate = _formal(site)
    subject = fresh(DictValue, ((StringValue("a"), TermValue(1)),))

    _assert_undecided_read(_read(subject, key, site, None), site)


def test_a_match_projection_composes_the_undecided_read() -> None:
    """A pattern's read at a parameter key runs the pattern's next step on
    the read's completed face; its halt face stands."""
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import Completed
    from sugar_lift_py_tests.sugar.match_sugar import _each, _read

    site = _site()
    key, _coordinate = _formal(site)
    subject = fresh(DictValue, ((StringValue("a"), TermValue(1)),))

    exits = _each(
        _read(subject, key, site, None),
        lambda item: ExitSet.completed(("item", item)),
    )

    _assert_undecided_read(exits, site)
    (done,) = [arm for arm in exits.exits if isinstance(arm, Completed)]
    assert done.value[0] == "item"


def test_a_walrus_read_with_a_parameter_index_is_the_undecided_read() -> None:
    from sugar_lift_py_tests.floor.named_expression_value import (
        NamedExpressionValue,
    )

    site = _site()
    index, _coordinate = _formal(site)
    walrus = NamedExpressionValue("ys", fresh(ListValue, (TermValue(1), TermValue(2))))

    _assert_undecided_read(walrus.subscript(index, site), site)


def test_a_guarded_parameter_arm_is_the_undecided_read_through_the_door() -> None:
    """``(xs if c else (5,))[0]``: each arm is read through the one door, so
    the parameter arm is the undecided read under its polarity, beside the
    other arm's read under its own; nothing waits on the caller."""
    from sugar_lift_py_tests.floor import GuardedValue
    from sugar_lift_py_tests.ir import atomic, not_
    from sugar_lift_py_tests.operations.subscript_operation import (
        discharge_subscript,
    )
    from sugar_lift_py_tests.outcome import Completed

    site = _site()
    receiver, _coordinate = _formal(site, "xs", 0)
    guard = atomic("chosen", [])
    guarded = GuardedValue(guard, receiver, _tuple(5))

    exits = discharge_subscript(
        guarded, TermValue(0), site, None, owner="SubscriptSugar"
    )

    _assert_undecided_read(exits, site, completed=2)
    assert (not_(guard), TermValue(5)) in {
        (face.guard, face.value)
        for face in exits.exits
        if isinstance(face, Completed)
    }


def test_a_parameter_receiver_read_is_the_undecided_read() -> None:
    """``p[0]`` and ``p[1:]`` on a parameter: nothing decides ``type(p)`` or
    its ``__getitem__``, and an item read gives ``p`` no class input
    (``nodes._receiver_class_parameters``), so the read is the one undecided
    read -- never a ``subscript`` carrier."""
    from sugar_lift_py_tests.floor.slice_value import SliceValue
    from sugar_lift_py_tests.operations.subscript_operation import (
        discharge_subscript,
    )

    site = _site()
    receiver, _coordinate = _formal(site, "xs", 0)

    for index in (TermValue(0), SliceValue(TermValue(1), None, None)):
        _assert_undecided_read(
            discharge_subscript(receiver, index, site, None, owner="SubscriptSugar"),
            site,
        )


def test_the_subscript_mint_and_its_projector_are_gone() -> None:
    """The deferred read is deleted (#7757, audit 2 row NEW-1): no
    ``defer_formal_subscript`` mint, and no carrier to mint it onto."""
    from sugar_lift_py_tests import caller_parameter_contract
    from sugar_lift_py_tests.operations import subscript_operation

    assert not hasattr(subscript_operation, "defer_formal_subscript")
    assert not hasattr(caller_parameter_contract, "NativeOperationExitCarrierV1")


# ---------------------------------------------------------------------------
# A parameter in a slice bound: the slice completes, its reader reads it
# ---------------------------------------------------------------------------


def _tuple(*values: int) -> TupleValue:
    return TupleValue(tuple(TermValue(value) for value in values))


def test_a_parameter_slice_bound_completes_the_slice() -> None:
    """``BUILD_SLICE`` never raises: a parameter bound stands in the slice
    as its symbolic value, and no ``slice`` carrier is minted."""
    from sugar_lift_py_tests.floor.slice_value import SliceValue, construct_slice

    site = _site()
    start, _coordinate = _formal(site, "start", 0)

    outcome = construct_slice(start, None, None)

    assert outcome.completed_value() == SliceValue(start, None, None)


def test_a_slice_with_no_parameter_bound_completes_here() -> None:
    from sugar_lift_py_tests.floor.slice_value import SliceValue, construct_slice

    outcome = construct_slice(TermValue(1), None, None)

    assert outcome.completed_value() == SliceValue(TermValue(1), None, None)


def test_a_parameter_slice_read_is_the_undecided_read() -> None:
    """``(0, 1, 2)[start:]``: the tuple's own read, whose bound's type
    nothing here decides -- the undecided read, its halt kept.  The same
    read at a decided bound 1 is ``(1, 2)``."""
    from sugar_lift_py_tests.floor.slice_value import construct_slice
    from sugar_lift_py_tests.operations.subscript_operation import (
        discharge_subscript,
    )

    site = _site()
    start, _coordinate = _formal(site, "start", 0)

    def read(bound):
        return construct_slice(bound, None, None).and_then(
            lambda index: discharge_subscript(
                _tuple(0, 1, 2), index, site, None, owner="SubscriptSugar"
            )
        )

    _assert_undecided_read(read(start), site)
    assert read(TermValue(1)).completed_value() == _tuple(1, 2)


def test_a_source_parameter_slice_bound_is_read_with_its_halt_kept() -> None:
    """``def tail(start): return (0, 1, 2)[start:]``: no ``slice`` carrier;
    the read keeps an undetermined halt."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome.exit_set import Halted

    source = "def tail(start):\n    return (0, 1, 2)[start:]\n"
    tree = _tree(source, "parameter-slice-helper.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))

    outcome = function.sugar().desugar(None)

    assert any(
        isinstance(arm, Halted) and isinstance(arm.effect, UndeterminedRaiseEffect)
        for arm in outcome.exits
    ), outcome
