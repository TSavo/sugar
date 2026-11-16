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

Getter-only property stays named AttributeError (store path, not read).
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


def test_star_values_reach_declared_stored_value() -> None:
    helper, receiver = _source_class_and_helper("    pass\n", HELPER_STAR)
    pack = TupleValue((TermValue(1), TermValue(2)))
    exits = _stored(helper, receiver, pack)
    assert isinstance(exits, ExitSet)
    assert isinstance(exits.exits[0], Completed)
    stored = exits.exits[0].value
    assert isinstance(stored, ObjectValue)
    assert stored.fields[-1].name == "field"
    assert stored.fields[-1].value == pack


def test_kw_values_reach_declared_stored_value() -> None:
    helper, receiver = _source_class_and_helper("    pass\n", HELPER_KW)
    mapping = fresh(DictValue, ((StringValue("a"), TermValue(1)),))
    exits = _stored(helper, receiver, mapping)
    assert isinstance(exits.exits[0], Completed)
    stored = exits.exits[0].value
    assert isinstance(stored, ObjectValue)
    assert stored.fields[-1].name == "field"
    assert stored.fields[-1].value == mapping


def test_empty_star_stores_honest_empty_tuple() -> None:
    helper, receiver = _source_class_and_helper("    pass\n", HELPER_STAR)
    exits = _stored(helper, receiver, TupleValue(()))
    assert isinstance(exits.exits[0], Completed)
    assert exits.exits[0].value.fields[-1].value == TupleValue(())


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
# Getter-only stays named AttributeError
# ---------------------------------------------------------------------------


def test_getter_only_property_named_attributeerror_with_star_pack() -> None:
    helper, receiver = _source_class_and_helper(
        "    @property\n" "    def field(self):\n" "        return 1\n",
        HELPER_STAR,
    )
    exits = _stored(helper, receiver, TupleValue((TermValue(9),)))
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert not isinstance(halted, Completed)
    assert halted.effect.exception_type_coordinate == _identity("AttributeError")
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    # The carrier's pre-effect state is gone with the carrier (#7757 NEW-1):
    # the helper's own store halt keeps the block's record as its state
    # (``_undecided_store`` in ``_source_class_and_helper``).


def test_getter_only_discrimination_not_completed() -> None:
    helper, receiver = _source_class_and_helper(
        "    @property\n" "    def field(self):\n" "        return 1\n",
        HELPER_KW,
    )
    exits = _stored(
        helper, receiver, fresh(DictValue, ((StringValue("a"), TermValue(1)),))
    )
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Completed)


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
