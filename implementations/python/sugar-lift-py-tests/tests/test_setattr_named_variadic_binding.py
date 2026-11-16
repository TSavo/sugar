"""Variadic binding through a field store on a formal.

Concrete signatures:

    def helper(obj, *values):
        obj.field = values

    def helper(obj, **values):
        obj.field = values

The store is the one attribute mutation (``store_effect_sugar.
attribute_mutation``, #7757 NEW-1): on the formal ``obj`` it is the undecided
store, never a carrier waiting on a caller's actuals.  *values / **values
reach the declared stored value without self/name shifting:
  - the store's completes atom names the receiver formal ``obj`` and the
    static name ``"field"`` -- never the pack, never a phantom self
  - the value is the variadic pack (TupleValue / DictValue) the binder packs
  - no phantom self/name formal steals the pack slot

What a caller supplies is stored through the same door: on a source
instance the store is ``type(obj).__setattr__`` (#7757 H1b).  Where the
instance's class names no join symbol (these trees have no workspace root)
it is the one unanswered call, two-faced and owed, carrying the pack as the
stored value.  The lift decides neither the plain store nor a getter-only
property's ``AttributeError``: prove does, and the call's halt is kept.
"""

from __future__ import annotations

import pytest

from frame_fresh import FRAME_FRESH, fresh
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    DictValue,
    ObjectValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.ir import str_const
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar import store_effect_sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, ClassDef, FunctionDef
from sugar_source_tree.tree import SourceFile

HELPER_STAR = "def helper(obj, *values):\n    obj.field = values\n"
HELPER_KW = "def helper(obj, **values):\n    obj.field = values\n"


def _tree(source: str, name: str = "setattr_variadic.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper(program: str):
    tree = _tree(program, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def _undecided_store(outcome) -> Halted:
    """The undecided attribute store in a helper's own proof: no carrier,
    one ``UndeterminedRaiseEffect`` halt owned by ``UndecidedSetattr`` kept
    with the state the store began from (the block's record), the undecided
    member owed on every face, never a completion."""
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


def _setattr_atoms(outcome):
    """Every ``python:setattr(<receiver>, <name>, <occurrence>)`` operation
    the completed faces' guards name (the undecided store's completes atom)."""

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

    return [
        atom
        for face in outcome.exits
        if isinstance(face, Completed)
        for atom in walk(face.guard)
    ]


def _stored(function, receiver, value):
    """``receiver.field = value`` through the one attribute mutation at the
    helper's store site, the receiver and the pack values the lift decides
    (what a caller supplies and the binder packs)."""
    return store_effect_sugar.attribute_mutation(
        "__setattr__",
        receiver,
        "field",
        (value,),
        function.body[0].fragment,
        None,
        unit=None,
    )


def _source_class_and_helper(class_body: str, helper_source: str, field: str = "field"):
    source = f"class Widget:\n{class_body}\n{helper_source}"
    tree = _tree(source, "source_class_setattr_var.py")
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
# Helper alone → the undecided store over obj; no self/name shifting
# ---------------------------------------------------------------------------


def test_helper_star_alone_is_undecided_store_without_self_name_shift() -> None:
    function, outcome = _helper(HELPER_STAR)
    _undecided_store(outcome)
    # The store names the receiver formal ``obj`` and the static name, not
    # the ``*values`` pack.
    atoms = _setattr_atoms(outcome)
    assert atoms, outcome
    for atom in atoms:
        receiver, name, _key = atom.args
        assert getattr(receiver, "name", None) == "obj", receiver
        assert name == str_const("field")
    kinds = tuple(c.parameter_kind for c in function.sugar().formal_coordinates)
    names = tuple(c.declared_name for c in function.sugar().formal_coordinates)
    assert kinds == ("positional-or-keyword", "variadic-positional")
    assert names == ("obj", "values")
    # Exactly two formals — no phantom self or name formal.
    assert len(function.sugar().formal_coordinates) == 2


def test_helper_kw_alone_is_undecided_store_without_self_name_shift() -> None:
    function, outcome = _helper(HELPER_KW)
    _undecided_store(outcome)
    atoms = _setattr_atoms(outcome)
    assert atoms, outcome
    for atom in atoms:
        receiver, name, _key = atom.args
        assert getattr(receiver, "name", None) == "obj", receiver
        assert name == str_const("field")
    kinds = tuple(c.parameter_kind for c in function.sugar().formal_coordinates)
    assert kinds == ("positional-or-keyword", "variadic-keyword")
    assert len(function.sugar().formal_coordinates) == 2


def test_helper_alone_is_not_completed_discrimination() -> None:
    _, outcome = _helper(HELPER_STAR)
    with pytest.raises(AssertionError):
        assert outcome.completed_value() is not None


# ---------------------------------------------------------------------------
# *values / **values reach the declared stored value
# ---------------------------------------------------------------------------


def _setattr_calls(exits: ExitSet):
    """Every ``call:Widget.__setattr__(<receiver>, <name>, <value>)`` term
    the completed faces' guards name: the one call the store is."""

    def walk(node, depth=0):
        if getattr(node, "name", None) == "call:Widget.__setattr__":
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


def _the_store_is_the_call(exits, value, site) -> None:
    """``receiver.field = value`` on a ``Widget`` whose class names no join
    symbol is ``type(receiver).__setattr__``, the one unanswered call
    (``ObjectValue.field_store_call``, #7757 H1b): two-faced, every face
    owed.  The value the binder packed reaches the call as its stored value,
    under the static name.  The lift never decides the plain store -- no
    completed face holds the instance with ``field`` stored -- nor a
    property's ``AttributeError`` -- no halt names it; the halt is kept."""
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
    for call in _setattr_calls(exits):
        assert call.args[1:3] == (
            StringValue("field").to_term(owner=owner),
            value.to_term(owner=owner),
        ), call


def test_star_values_reach_declared_stored_value() -> None:
    """Expected verdict changed (#7757 H1b, #9065): the pack reaches the
    store's call, not a field the lift decided stored."""
    helper, receiver = _source_class_and_helper("    pass\n", HELPER_STAR)
    pack = TupleValue((TermValue(1), TermValue(2)))
    _the_store_is_the_call(
        _stored(helper, receiver, pack), pack, helper.body[0].fragment
    )


def test_kw_values_reach_declared_stored_value() -> None:
    helper, receiver = _source_class_and_helper("    pass\n", HELPER_KW)
    mapping = fresh(DictValue, ((StringValue("a"), TermValue(1)),))
    _the_store_is_the_call(
        _stored(helper, receiver, mapping), mapping, helper.body[0].fragment
    )


def test_empty_star_stores_honest_empty_tuple() -> None:
    helper, receiver = _source_class_and_helper("    pass\n", HELPER_STAR)
    _the_store_is_the_call(
        _stored(helper, receiver, TupleValue(())),
        TupleValue(()),
        helper.body[0].fragment,
    )


def test_a_star_pack_is_not_the_store_s_name_discrimination() -> None:
    """Bite: the pack is the call's stored value, never its name operand."""
    helper, receiver = _source_class_and_helper("    pass\n", HELPER_STAR)
    pack = TupleValue((TermValue(1), TermValue(2)))
    owner = str(helper.body[0].fragment)
    for call in _setattr_calls(_stored(helper, receiver, pack)):
        assert call.args[1] != pack.to_term(owner=owner), call


def _applied_frame(program: str):
    """The frame the program's last call applies: ``helper``'s own.

    A call of a plain ``def`` seats no frame by its name (#8647): it is the
    call of the function the ``def`` statement built (``ComputedCallSugar``),
    which applies its definition's own frame
    (``LambdaCallable.source_call_frame``) and binds the actuals there.
    The call sits in a caller's body: a call the module body
    runs is answered as the module-level read is, not at all (#9007
    decision 1)."""
    from sugar_lift_py_tests.sugar.computed_call_sugar import ComputedCallSugar

    tree = _tree(program)
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    sugar = call.sugar()
    assert isinstance(sugar, ComputedCallSugar), sugar
    assert sugar.source_call_frame is None
    helper = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "helper"
    )
    return helper.source_visible_call_frame()


def test_bind_actuals_packs_star_without_self_name_shift() -> None:
    """SourceCallFrame.bind_actuals packs remaining positionals into *values.

    Frame parameters are exactly ``(obj, values)`` — no phantom self/name
    formal steals the pack slot (the attribute name is static).
    """
    from sugar_lift_py_tests.floor import ListValue

    frame = _applied_frame(
        HELPER_STAR + "\ndef caller():\n    return helper([0], 1, 2, 3)\n"
    )
    assert frame.parameters == ("obj", "values")
    assert frame.parameter_kinds == ("positional_or_keyword", "vararg")
    bound = frame.bind_actuals(
        (fresh(ListValue, (TermValue(0),)), TermValue(1), TermValue(2), TermValue(3)),
        (),
    )
    assert bound.actuals == (
        fresh(ListValue, (TermValue(0),)),
        TupleValue((TermValue(1), TermValue(2), TermValue(3))),
    )
    # Two bound slots only — pack is values, not shifted by self/name.
    assert len(bound.actuals) == 2


def test_bind_actuals_packs_kw_without_self_name_shift() -> None:
    """SourceCallFrame.bind_actuals packs extra keywords into **values."""
    from sugar_lift_py_tests.floor import ListValue

    frame = _applied_frame(
        HELPER_KW + "\ndef caller():\n    return helper([0], a=1, b=2)\n"
    )
    assert frame.parameters == ("obj", "values")
    assert frame.parameter_kinds == ("positional_or_keyword", "kwarg")
    bound = frame.bind_actuals(
        (fresh(ListValue, (TermValue(0),)),),
        (("a", TermValue(1)), ("b", TermValue(2))),
    )
    assert bound.actuals == (
        fresh(ListValue, (TermValue(0),)),
        fresh(
            DictValue,
            (
                (StringValue("a"), TermValue(1)),
                (StringValue("b"), TermValue(2)),
            ),
        ),
    )
    assert len(bound.actuals) == 2


# ---------------------------------------------------------------------------
# Getter-only: the call, its halt kept; never a lift AttributeError
# ---------------------------------------------------------------------------


def test_getter_only_property_store_with_star_pack_is_the_call() -> None:
    """Python's store raises ``AttributeError`` on a getter-only property.
    Expected verdict changed (#7757 H1b, #9065): the lift no longer names
    that halt (``ObjectValue.setattr``'s lift-decided ``AttributeError`` is
    deleted); the store is the call, its halt kept and owed, decided at
    prove.  The helper's own store halt keeps the block's record as its
    state (``_undecided_store`` in ``_source_class_and_helper``)."""
    helper, receiver = _source_class_and_helper(
        "    @property\n" "    def field(self):\n" "        return 1\n",
        HELPER_STAR,
    )
    pack = TupleValue((TermValue(9),))
    _the_store_is_the_call(
        _stored(helper, receiver, pack), pack, helper.body[0].fragment
    )


def test_getter_only_discrimination_not_completed() -> None:
    """Bite: the getter licenses no completed store -- no face holds the
    instance with the mapping stored."""
    helper, receiver = _source_class_and_helper(
        "    @property\n" "    def field(self):\n" "        return 1\n",
        HELPER_KW,
    )
    mapping = fresh(DictValue, ((StringValue("a"), TermValue(1)),))
    exits = _stored(helper, receiver, mapping)
    with pytest.raises(AssertionError):
        assert any(
            isinstance(face, Completed)
            and isinstance(face.value, ObjectValue)
            and any(f.name == "field" for f in face.value.fields)
            for face in exits.exits
        )


def test_no_self_name_shift_receiver_discrimination() -> None:
    """Bite: the store's receiver is ``obj``, its name the static
    ``"field"``; never the pack, never a formal name."""
    _, outcome = _helper(HELPER_STAR)
    atoms = _setattr_atoms(outcome)
    assert atoms, outcome
    receiver, name, _key = atoms[0].args
    with pytest.raises(AssertionError):
        assert getattr(receiver, "name", None) == "values"
    with pytest.raises(AssertionError):
        assert name != str_const("field")
