"""A field store on a method's formal, beside a bound-method receiver.

Concrete program:

    class Writer:
        def store(self, obj, value):
            obj.field = value

    Writer().store(target, 7)

Python law: a bound method call supplies ``self`` first. That binding must not
shift ``obj`` / ``value`` in the store: the store is ``type(obj).__setattr__(
obj, "field", value)``; ``self`` is the method binder's slot, not a store
operand.

The store is the one attribute mutation (``store_effect_sugar.
attribute_mutation``, #7757 NEW-1): in the method's own proof it is the
undecided store over ``obj`` -- never a carrier waiting on a caller's actuals
(the ``setattr_named`` carrier is deleted).  What a caller supplies is stored
through the same door, the floor's own store with every face kept.

Acceptance (each with a discrimination twin where noted):

  1. Bound ``self`` is not the store's receiver: the store names ``obj``.
  2. Method alone is the undecided store, its halt kept, owed.
  3. On a receiver a caller supplies, the store is ``type(obj).__setattr__``
     (#7757 H1b): where the instance's class names no join symbol (these
     trees have no workspace root), the one unanswered call, two-faced and
     owed, carrying ``obj``'s value and the stored value.  The lift decides
     neither a plain store (no completed face holds the field stored) nor a
     getter-only property's ``AttributeError`` (no halt names it): prove
     does, and the call's halt is kept.
  4. Off-by-one self-binding and read-authorizes-write twins fail.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import ObjectValue, StringValue, TermValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.ir import str_const
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar import store_effect_sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef, FunctionDef
from sugar_source_tree.tree import SourceFile

from frame_fresh import FRAME_FRESH

METHOD_BODY = (
    "class Writer:\n" "    def store(self, obj, value):\n" "        obj.field = value\n"
)

# Empty writable class used as the store *target* (obj), not the method binder.
TARGET_CLASS = "class Target:\n    pass\n"

# Property getter without setter — store path must AttributeError.
PROPERTY_TARGET = (
    "class Target:\n" "    @property\n" "    def field(self):\n" "        return 1\n"
)


def _tree(source: str, name: str = "setattr_method_caller.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _method_definition(source: str = METHOD_BODY):
    tree = _tree(source, "method_alone.py")
    class_def = next(node for node in tree.nodes() if isinstance(node, ClassDef))
    method = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "store"
    )
    return class_def, method, method.sugar().desugar(None)


def _construct_class(source: str, class_name: str) -> ObjectValue:
    tree = _tree(source, f"{class_name.lower()}_class.py")
    class_def = next(
        node
        for node in tree.nodes()
        if isinstance(node, ClassDef) and node.name == class_name
    )
    class_outcome = class_def.sugar().desugar(None)
    class_value = class_outcome.completed_value()
    assert isinstance(class_value, ClassDefinitionValue)
    receiver = class_value.fresh_receiver(
        class_value.class_definition_cid, allocation=FRAME_FRESH
    )
    assert isinstance(receiver, ObjectValue)
    return receiver


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def _undecided_store(outcome) -> Halted:
    """The undecided attribute store in the method's own proof: no carrier,
    one ``UndeterminedRaiseEffect`` halt owned by ``UndecidedSetattr`` kept
    with the state the store began from, the undecided member owed on every
    face, never a completion."""
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


def _store_receivers(outcome):
    """``(<receiver>, <name>)`` of every ``python:setattr(<receiver>,
    <name>, <occurrence>)`` the completed faces' guards name: the undecided
    store's completes atom."""

    def walk(node, depth=0):
        if getattr(node, "name", None) == "python:setattr":
            yield node
        if depth > 64:
            return
        for child in (
            *(getattr(node, "args", ()) or ()),
            *(getattr(node, "operands", ()) or ()),
        ):
            yield from walk(child, depth + 1)

    pairs = [
        (atom.args[0], atom.args[1])
        for face in outcome.exits
        if isinstance(face, Completed)
        for atom in walk(face.guard)
    ]
    assert pairs, outcome
    return pairs


def _stored(method, receiver, value):
    """``receiver.field = value`` through the one attribute mutation at the
    method's store site, the receiver a value the lift decides (what a
    caller supplies)."""
    return store_effect_sugar.attribute_mutation(
        "__setattr__",
        receiver,
        "field",
        (value,),
        method.body[0].fragment,
        None,
        unit=None,
    )


def _setattr_calls(exits: ExitSet, class_name: str):
    """Every ``call:<class_name>.__setattr__(<receiver>, <name>, <value>)``
    term the completed faces' guards name: the one call the store is."""
    target = f"call:{class_name}.__setattr__"

    def walk(node, depth=0):
        if getattr(node, "name", None) == target:
            yield node
        if depth > 64:
            return
        for child in (
            *(getattr(node, "args", ()) or ()),
            *(getattr(node, "operands", ()) or ()),
        ):
            yield from walk(child, depth + 1)

    calls = [
        call
        for face in exits.exits
        if isinstance(face, Completed)
        for call in walk(face.guard)
    ]
    assert calls, exits
    return calls


def _the_store_is_the_call(exits, value, site, class_name: str = "Target") -> None:
    """``receiver.field = value`` on an instance whose class names no join
    symbol is ``type(receiver).__setattr__``, the one unanswered call
    (``ObjectValue.field_store_call``, #7757 H1b): two-faced, every face
    owed.  The lift never decides the plain store -- no completed face
    holds the instance with ``field`` stored -- nor a property's
    ``AttributeError`` -- no halt names it; the call's halt is kept.  The
    call carries the static name and the value the store hands it."""
    from sugar_lift_py_tests.floor.object_identity import contents_current

    assert isinstance(exits, ExitSet), type(exits)
    assert exits.halts(), exits
    for halt in exits.halts():
        assert getattr(halt.effect, "exception_name", None) != "AttributeError", (
            halt.effect
        )
        assert getattr(
            halt.effect, "exception_type_coordinate", None
        ) != _identity("AttributeError"), halt.effect
        assert halt.owed, halt
    for face in exits.exits:
        assert face.owed, face
        if not isinstance(face, Completed):
            continue
        stored = face.value
        assert not (
            isinstance(stored, ObjectValue)
            and contents_current(stored)
            and any(f.name == "field" and f.value == value for f in stored.fields)
        ), stored
    owner = str(site)
    for call in _setattr_calls(exits, class_name):
        assert call.args[1:3] == (
            StringValue("field").to_term(owner=owner),
            value.to_term(owner=owner),
        ), call


# ---------------------------------------------------------------------------
# 1. Bound self is not the store's receiver
# ---------------------------------------------------------------------------


def test_method_alone_stores_on_obj_not_self() -> None:
    """Method body ``obj.field = value``: the undecided store names ``obj``
    and the static name, never ``self``."""
    _class_def, method, outcome = _method_definition()
    _undecided_store(outcome)
    for receiver, name in _store_receivers(outcome):
        assert getattr(receiver, "name", None) == "obj", receiver
        assert name == str_const("field")
    method_formals = tuple(p.name for p in method.params)
    assert method_formals[0] == "self"
    assert method_formals[1:] == ("obj", "value")


def test_discrimination_self_is_not_the_setattr_receiver() -> None:
    """Bite: the store's receiver must not be the method's self formal."""
    _class_def, _method, outcome = _method_definition()
    receivers = {getattr(r, "name", None) for r, _name in _store_receivers(outcome)}
    assert "self" not in receivers
    assert "value" not in receivers


# ---------------------------------------------------------------------------
# 2. Method alone is the undecided store
# ---------------------------------------------------------------------------


def test_method_alone_is_the_undecided_store_not_a_carrier() -> None:
    _, _method, outcome = _method_definition()
    _undecided_store(outcome)
    assert not hasattr(store_effect_sugar, "mint_setattr_named_carrier")


def test_discrimination_method_alone_is_not_completed() -> None:
    """Bite: the undecided store is no unconditional completion."""
    _, _method, outcome = _method_definition()
    assert outcome.completed_value() is None
    assert outcome.halts()


# ---------------------------------------------------------------------------
# 3. What a caller supplies, through the one door
# ---------------------------------------------------------------------------


def test_writable_receiver_store_is_the_call_through_the_door() -> None:
    """Expected verdict changed (#7757 H1b, #9065): the store on a writable
    instance no longer completes with the field stored as the lift decided
    it; it is ``type(obj).__setattr__``, owed, which prove decides."""
    _, method, _outcome = _method_definition()
    target = _construct_class(TARGET_CLASS, "Target")
    assert target.methods == ()
    _the_store_is_the_call(
        _stored(method, target, TermValue(7)),
        TermValue(7),
        method.body[0].fragment,
    )


def test_getter_only_property_store_is_the_call_its_halt_kept() -> None:
    """A getter-only property: Python's store raises ``AttributeError``.
    Expected verdict changed (#7757 H1b, #9065): the lift no longer names
    that halt (``ObjectValue.setattr``'s lift-decided ``AttributeError`` is
    deleted); the store is the call, whose halt is kept, owed, and decided at
    prove.  The wrong-boundary retention of the lift's named halt has no
    named halt left to retain (as #9065 deleted for the formal caller); the
    method's own store halt keeps the block's record (``_undecided_store``)."""
    _, method, outcome = _method_definition()
    _undecided_store(outcome)
    target = _construct_class(PROPERTY_TARGET, "Target")
    assert any(
        m.name == "field" and m.descriptor_kind == "property" for m in target.methods
    )
    _the_store_is_the_call(
        _stored(method, target, TermValue(7)),
        TermValue(7),
        method.body[0].fragment,
    )


def test_read_does_not_authorize_completed_store_on_getter_only_property() -> None:
    """Lying twin: the property is readable, but the read licenses no
    completed store: no face holds the instance with the field stored."""
    _, method, _outcome = _method_definition()
    target = _construct_class(PROPERTY_TARGET, "Target")
    # Readable property is enrolled.
    assert any(
        m.name == "field" and m.descriptor_kind == "property" for m in target.methods
    )
    _the_store_is_the_call(
        _stored(method, target, TermValue(99)),
        TermValue(99),
        method.body[0].fragment,
    )


def test_discrimination_writable_store_is_not_read_authorized_halt() -> None:
    """Positive twin of read-authorizes-write: empty class completes."""
    _, method, _outcome = _method_definition()
    target = _construct_class(TARGET_CLASS, "Target")
    exits = _stored(method, target, TermValue(99))
    assert isinstance(exits.exits[0], Completed)
    assert not isinstance(exits.exits[0], Halted)
