"""Vertical completion: a field store on a formal through the one attribute
mutation.

Python semantic law made constructible:

  For ``helper(obj, value)`` whose body is ``obj.field = value``, the store
  dispatches ``__setattr__`` / descriptor ``__set__`` — a different method and
  obligation from the read path.  Helper alone stays owed.  An ordinary
  source caller (positional, keyword, or default) supplies authenticated
  actuals; the store on what the caller passes projects Completed field
  stores or named exceptional faces whose origin is Floor ``setattr``, never
  an enclosing boundary type.

Every attribute store is the one attribute mutation (``store_effect_sugar.
attribute_mutation``, #7757 step 7), never a carrier waiting on a caller's
actuals (the ``setattr_named`` carrier is deleted):

  - ``obj`` above is stored into and used no other way, so its class is an
    input of ``helper``'s contract and the store is the undecided store
    (``undecided_attribute_mutation_faces``): it completes under
    ``or(python:plain_store(class:obj, "field"), python:setattr.completes(
    ...))`` -- the plain ``__dict__`` store prove decides on the class each
    caller binds -- and raises something undetermined under the complement,
    both faces owing the undecided member.
  - On a receiver whose type the lift decides (an object a caller built, a
    tuple, ``None``) it is the floor's own store, every face kept; the floor
    tests below read it through the same door (``_stored``).

Source-defined class vertical (the three acceptance faces):

  writable field          → Completed
  property getter, no set → named AttributeError (store path, not read)
  wrong boundary type     → exceptional edge remains unconsumed

Corpus (pandas 3.0.3, content verified on installed seat):

  ``compat/__init__.py:52`` in ``set_function_name`` @48:
      ``f.__name__ = name``  (formal ``f`` store)
  ``core/indexes/base.py:4267`` in ``_maybe_preserve_names`` @4264:
      ``target.name = self.name``  (formal ``target`` store)
"""

from __future__ import annotations

from dataclasses import dataclass

from frame_fresh import FRAME_FRESH
from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    NoneValue,
    ObjectField,
    ObjectMethodValue,
    ObjectValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar import store_effect_sugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef, FunctionDef
from sugar_source_tree.tree import SourceFile

MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)


def _identity(name: str):
    coordinate, _ = _builtin_exception_identity(name)
    return coordinate


def _tree(source: str, name: str = "setattr_caller.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper_definition():
    """``helper`` alone and its own proof's reduction: ``obj.field = value``
    on a formal whose class is an input of the contract is the undecided
    store, completing also where prove decides the store plain."""
    source = "def helper(obj, value):\n    obj.field = value\n"
    tree = _tree(source, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _names(term, depth=0):
    """Every constructor and atom name in ``term``, at any depth."""
    names = {getattr(term, "name", None)}
    if depth > 64:
        return names
    children = (
        *(getattr(term, "args", ()) or ()),
        *(getattr(term, "operands", ()) or ()),
    )
    body = getattr(term, "body", None)
    for child in (*children, *(() if body is None else (body,))):
        names |= _names(child, depth + 1)
    return names


def _undecided_store(outcome) -> Halted:
    """The undecided attribute store (``undecided_attribute_mutation_faces``)
    in a helper's own proof: no carrier, one ``UndeterminedRaiseEffect`` halt
    owned by ``UndecidedSetattr`` kept with the state the store began from,
    and every completed face and the halt owing the undecided member at the
    store's site -- owed, never a completion."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls, unanswered_call

    assert isinstance(outcome, ExitSet), type(outcome)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UndecidedSetattr"
    ]
    assert len(halts) == 1, outcome
    (halt,) = halts
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.state is not None
    owed = unanswered_call(None, halt.effect.site)
    assert owed in owed_calls(outcome)
    assert owed in halt.owed
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    assert all(owed in face.owed for face in completed)
    assert outcome.completed_value() is None
    return halt


def _stored(function, receiver, value):
    """``receiver.field = value`` through the one attribute mutation at the
    helper's store site, the receiver a value the lift decides (what a
    caller supplies): the floor's own store, every face kept."""
    return store_effect_sugar.attribute_mutation(
        "__setattr__",
        receiver,
        "field",
        (value,),
        function.body[0].fragment,
        None,
        unit=None,
    )


def _caller_edge(signature: str, actuals: str):
    """``helper({actuals})`` in a caller's body, read off the caller's
    contract row (``function_universe_outcome``).

    A same-file call is its coordinate and edge, joined at prove (#7757
    steps 5 and 6, #8705): the helper's store never waits on the call's
    actuals.  The call completes under its ``completes`` atom and halts
    under the complement; the named ``AttributeError`` the helper's store
    raises for ``1.field = 2`` is its panic locus, which prove joins at the
    call (#8690) with the type the contract states (#8749).  Returns the
    row's outcome and the call value its one completed face returns."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    source = (
        f"def helper({signature}):\n"
        "    obj.field = value\n\n"
        f"def caller():\n    return helper({actuals})\n"
    )
    tree = _tree(source)
    caller = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "caller"
    )
    outcome = function_universe_outcome(caller)
    assert [face for face in outcome.exits if isinstance(face, Halted)], outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    returns = [
        s for s in completed[0].value.record.statements if isinstance(s, ReturnValue)
    ]
    assert returns, completed[0].value
    edge = returns[-1].value
    assert isinstance(edge, CallSiteValue), type(edge)
    return outcome, edge


def _coordinate(edge):
    """The call's coordinate ``call:<target>(<arguments>)`` the edge's value
    names: the completed face of the one unanswered call returns
    ``python:call_result(<call term>, <occurrence>)`` (#7757 steps 5 and 6,
    #8705), so the arguments prove's binder binds are the call term's,
    never the result's."""
    result = edge.term
    assert result.name == "python:call_result", result
    call = result.args[0]
    assert call.name.startswith("call:"), call
    return call


def _int(edge, value: int):
    return TermValue(value).to_term(owner=str(edge.site))


def _named(edge, kind: str, name: str, value: int):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(kind, [str_const(name), _int(edge, value)])


def _int_class(key: str):
    """``py.class(<key>, python:builtin("int"))``: the class of an ``int``
    actual the caller decides, keyed by the argument it is, after the
    actuals (#8857, ``receiver_dispatch.class_arguments``).  A default
    supplies none."""
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.receiver_dispatch import (
        CLASS_ARGUMENT,
        builtin_class_term,
    )

    return ctor(CLASS_ARGUMENT, [str_const(key), builtin_class_term("int")])


def _source_class_and_helper(class_body: str, field: str = "field"):
    """Build a source-defined class + formal store helper in one tree.

    Receivers for the store are constructed from the ClassDef floor value —
    the same door that source instantiation uses for method/descriptor
    enrollment — not hand-rolled ObjectValue fields.  The helper alone is
    the undecided store.
    """
    source = (
        f"class Widget:\n"
        f"{class_body}\n"
        f"def helper(obj, value):\n"
        f"    obj.{field} = value\n"
    )
    tree = _tree(source, "source_class_setattr.py")
    class_def = next(node for node in tree.nodes() if isinstance(node, ClassDef))
    helper = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "helper"
    )
    class_outcome = class_def.sugar().desugar(None)
    class_value = class_outcome.completed_value()
    assert isinstance(class_value, ClassDefinitionValue)
    receiver = class_value.fresh_receiver(
        class_value.class_definition_cid, allocation=FRAME_FRESH
    )
    assert isinstance(receiver, ObjectValue)
    _undecided_store(helper.sugar().desugar(None))
    return helper, receiver


# ---------------------------------------------------------------------------
# Helper alone → the undecided store, owed
# ---------------------------------------------------------------------------


def test_helper_alone_is_the_undecided_store() -> None:
    """``obj.field = value`` alone: the undecided store, its halt kept, owed.
    ``obj``'s class is an input of the contract, so the store completes also
    where prove decides it the plain ``__dict__`` store."""
    _, outcome = _helper_definition()
    _undecided_store(outcome)
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    for face in completed:
        names = _names(face.guard)
        assert "python:plain_store" in names, face.guard
        assert "python:setattr.completes" in names, face.guard


def test_field_store_mints_no_setattr_carrier() -> None:
    """The ``setattr_named`` carrier, its mint and its projector are deleted
    (#7757 NEW-1): no store waits on a caller's actual."""
    _, outcome = _helper_definition()
    assert not hasattr(store_effect_sugar, "mint_setattr_named_carrier")
    assert not hasattr(store_effect_sugar, "project_setattr")


def test_undecided_store_names_the_receiver_formal() -> None:
    """The store's completes atom is ``python:setattr(<obj>, "field",
    <occurrence>)``: the receiver formal and the static name, never the
    value."""
    from sugar_lift_py_tests.ir import str_const

    _, outcome = _helper_definition()
    _undecided_store(outcome)

    def atoms(node, depth=0):
        if getattr(node, "name", None) == "python:setattr":
            yield node
        if depth > 64:
            return
        for child in (
            *(getattr(node, "args", ()) or ()),
            *(getattr(node, "operands", ()) or ()),
        ):
            yield from atoms(child, depth + 1)

    stores = [
        atom
        for face in outcome.exits
        if isinstance(face, Completed)
        for atom in atoms(face.guard)
    ]
    assert stores, outcome
    for store in stores:
        receiver, name, _key = store.args
        assert getattr(receiver, "name", None) == "obj", receiver
        assert name == str_const("field")


# ---------------------------------------------------------------------------
# Source-defined class vertical — three acceptance faces
# ---------------------------------------------------------------------------


def _the_store_is_never_decided_here(exits, value) -> None:
    """``receiver.field = value`` on a source instance is
    ``type(receiver).__setattr__`` (#7757 H1b): the lift never decides that
    it is the plain store, nor that it raises ``AttributeError``.  The
    instance with the field stored is a completed face only under
    ``python:plain_store``, which prove decides; every other face is the
    call's, its halt kept."""
    from sugar_lift_py_tests.floor.object_identity import contents_current

    assert isinstance(exits, ExitSet)
    assert exits.halts(), exits
    for halt in exits.halts():
        assert getattr(halt.effect, "exception_name", None) != "AttributeError", (
            halt.effect
        )
    for face in exits.exits:
        if not isinstance(face, Completed) or "python:plain_store" in repr(
            face.guard
        ):
            continue
        stored = face.value
        assert not (
            isinstance(stored, ObjectValue)
            and contents_current(stored)
            and any(f.name == "field" and f.value == value for f in stored.fields)
        ), stored


def test_source_defined_writable_field_store_is_decided_at_prove() -> None:
    """A writable instance field on a source class: the plain store only
    under prove's ``python:plain_store``, the call otherwise."""
    helper, receiver = _source_class_and_helper("    pass\n")
    assert receiver.methods == ()
    _the_store_is_never_decided_here(
        _stored(helper, receiver, TermValue(7)), TermValue(7)
    )


def test_source_defined_property_without_setter_is_never_decided_here() -> None:
    """A getter-only property: Python's store raises ``AttributeError``;
    the lift decides neither that nor a completed store (the getter never
    licenses one)."""
    helper, receiver = _source_class_and_helper(
        "    @property\n" "    def field(self):\n" "        return 1\n"
    )
    assert any(
        m.name == "field" and m.descriptor_kind == "property" for m in receiver.methods
    )
    site = helper.body[0].fragment
    _the_store_is_never_decided_here(
        receiver.setattr("field", TermValue(7), site, None), TermValue(7)
    )
    _the_store_is_never_decided_here(
        _stored(helper, receiver, TermValue(99)), TermValue(99)
    )


# ---------------------------------------------------------------------------
# Real callers → Completed or named Exceptional
# ---------------------------------------------------------------------------


def test_object_receiver_store_is_the_call_never_decided_here() -> None:
    # Source-level int actuals hit TermValue.setattr → named AttributeError.
    # On an object the caller built the store is ``type(o).__setattr__``,
    # decided at prove (#7757 H1b), through the door.
    function, outcome = _helper_definition()
    _undecided_store(outcome)
    receiver = ObjectValue(
        "R", (ObjectField("field", TermValue(0)),), allocation=FRAME_FRESH
    )
    _the_store_is_never_decided_here(
        _stored(function, receiver, TermValue(7)), TermValue(7)
    )


def test_positional_caller_halts_with_named_identity_from_setattr() -> None:
    # Expected verdict changed (#7757 steps 5 and 6): the caller's row no
    # longer holds the named AttributeError as its one halt; the call's halt
    # is owed to the helper's contract, joined at prove.  The helper's own
    # store halt on a non-object receiver is
    # ``test_tuple_receiver_store_halts_from_setattr_not_boundary``.
    _outcome, edge = _caller_edge("obj, value", "1, 2")
    assert _coordinate(edge).args == (
        _int(edge, 1),
        _int(edge, 2),
        _int_class("0"),
        _int_class("1"),
    )
    # The halt prove joins at this call: the store with what the caller
    # supplies, ``1.field = 2``, is the named AttributeError at the store's
    # site -- the helper's panic locus.
    function, _ = _helper_definition()
    exits = _stored(function, TermValue(1), TermValue(2))
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("AttributeError")
    site = function.body[0].fragment
    assert halted.effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


def test_keyword_caller_reaches_same_demand() -> None:
    _outcome, edge = _caller_edge("obj, value", "obj=1, value=2")
    assert list(_coordinate(edge).args) == [
        _named(edge, "py.kwarg", "obj", 1),
        _named(edge, "py.kwarg", "value", 2),
        _int_class("obj"),
        _int_class("value"),
    ]


def test_default_value_caller_reaches_same_demand() -> None:
    # The call stands in a function called after import: the omitted
    # ``value`` binds what the ``def`` statement evaluated when the module
    # ran (``ModuleFinalValue``), and the edge carries it as ``py.default``.
    # A module-body call reduced alone is reached by no ``def`` statement's
    # run, and its default read is refused by name (``DefaultValueSugar``):
    # never the default expression evaluated again at the call.
    _outcome, edge = _caller_edge("obj, value=2", "1")
    assert list(_coordinate(edge).args) == [
        _int(edge, 1),
        _named(edge, "py.default", "value", 2),
        _int_class("0"),
    ]


def test_tuple_receiver_store_halts_from_setattr_not_boundary() -> None:
    function, _ = _helper_definition()
    exits = _stored(function, TupleValue((TermValue(1),)), TermValue(9))
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("AttributeError")
    # The store statement ``obj.field = value`` is the operation's site.
    site = function.body[0].fragment
    assert halted.effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"
    assert "AttributeError" in repr(halted.effect.exception_type_coordinate)
    # The statement form reaches the same door: the floor's own owner.
    from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
        ReceiverFieldStoreSugar,
    )
    from sugar_lift_py_tests.sugar.sugar_base import Sugar as _S

    @dataclass(frozen=True)
    class _V(_S):
        value: object

        def desugar(self, ctx=None):
            return ExitSet.completed(self.value)

        @classmethod
        def witnesses(cls):
            return ()

    direct = ReceiverFieldStoreSugar(
        _V(TupleValue((TermValue(1),))),
        _V(TermValue(9)),
        "field",
        site,
    ).desugar()
    assert direct.halts() == direct.exits
    (direct_halt,) = direct.halts()
    assert direct_halt.effect.producer_node_owner == "TupleValue.setattr"


# ---------------------------------------------------------------------------
# Property: readable ≠ settable through the store
# ---------------------------------------------------------------------------


def _getter_only_receiver():
    return ObjectValue(
        "R",
        (),
        methods=(
            ObjectMethodValue(
                name="field",
                parameters=("self",),
                descriptor_kind="property",
            ),
        ),
        allocation=FRAME_FRESH,
    )


def test_property_without_setter_reads_fine_and_halts_on_store() -> None:
    @dataclass(frozen=True)
    class _GetterBody(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return ExitSet.completed(
                BlockValue((ReturnValue(TermValue(1)),), can_fall_through=False)
            )

        @classmethod
        def witnesses(cls):
            return ()

    receiver = _getter_only_receiver()
    # Readable property is present as a data descriptor (getter enrolled).
    assert any(
        m.name == "field" and m.descriptor_kind == "property" for m in receiver.methods
    )

    # The store keeps its halt face -- never a completed field write
    # licensed by the getter, and never an ``AttributeError`` the lift
    # decides (#7757 H1b).
    function, _ = _helper_definition()
    site = function.body[0].fragment
    _the_store_is_never_decided_here(
        receiver.setattr("field", TermValue(7), site, None), TermValue(7)
    )
    _the_store_is_never_decided_here(
        _stored(function, receiver, TermValue(7)), TermValue(7)
    )


def test_lying_read_path_does_not_authorize_completed_store() -> None:
    """Borrowing __getattr__ evidence to complete a store must fail."""
    function, _ = _helper_definition()
    _the_store_is_never_decided_here(
        _stored(function, _getter_only_receiver(), TermValue(99)), TermValue(99)
    )


# ---------------------------------------------------------------------------
# Wrong boundary type: exceptional edge remains unconsumed
# ---------------------------------------------------------------------------


def test_wrong_expected_type_leaves_exceptional_edge_unconsumed() -> None:
    """Boundary verifies; it cannot create. Wrong T leaves the edge unconsumed."""
    from sugar_lift_py_tests.ir import ctor, str_const

    function, _ = _helper_definition()
    exits = _stored(function, NoneValue(), TermValue(1))
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    produced_type = halted.effect.exception_type_coordinate
    assert produced_type is not None

    # Boundary expects ValueError; store produced AttributeError.
    wrong = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("ValueError")],
    )
    # Equality of type coordinates is not origin — produced is AttributeError.
    assert produced_type != wrong
    # The exceptional edge is still present (unconsumed by a wrong boundary).
    assert isinstance(halted, Halted)
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )


# ---------------------------------------------------------------------------
# Corpus coordinates
# ---------------------------------------------------------------------------


def test_pinned_pandas_formal_attr_store_coordinates_are_real() -> None:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.file_count, corpus.manifest_cid) == (
        "3.0.3",
        1421,
        MANIFEST_CID,
    )
    install_root = corpus.root.parent
    cases = (
        (
            "pandas/compat/__init__.py",
            52,
            "f.__name__ = name",
            "set_function_name",
            48,
        ),
        (
            "pandas/core/indexes/base.py",
            4267,
            "target.name = self.name",
            "_maybe_preserve_names",
            4264,
        ),
    )
    for rel, line, text, fn_name, fn_line in cases:
        path = install_root / rel
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[line - 1].strip() == text, (rel, line, lines[line - 1])
        # Function def line verified.
        assert f"def {fn_name}" in lines[fn_line - 1], (
            rel,
            fn_line,
            lines[fn_line - 1],
        )
