"""Variadic binding through formal setattr_named.

Concrete signatures:

    def helper(obj, *values):
        obj.field = values

    def helper(obj, **values):
        obj.field = values

*values / **values reach the declared stored value without self/name shifting:
  - mint operands stay ``(receiver, StringValue(\"field\"), value_formal)``
  - name coordinate remains null (static attribute name, not a formal)
  - value formal is the variadic pack (TupleValue / DictValue)
  - no phantom self/name formal steals the pack slot

Getter-only property stays named AttributeError (store path, not read).

Does not touch carrier/ExitSet, store producer/projector/Floor; no second binder.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    DictValue,
    ObjectValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
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
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
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
    assert isinstance(class_outcome, Complete)
    assert isinstance(class_outcome.value, ClassDefinitionValue)
    receiver = class_outcome.value.construct_receiver_state_from_block(
        None, class_outcome.value.class_definition_cid
    )
    assert isinstance(receiver, ObjectValue)
    pending = helper.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setattr_named"
    return helper, pending, receiver


# ---------------------------------------------------------------------------
# Helper alone → Undischarged setattr_named; no self/name shifting
# ---------------------------------------------------------------------------


def test_helper_star_alone_undischarged_without_self_name_shift() -> None:
    function, pending = _helper(HELPER_STAR)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setattr_named"
    # Static name slot is null; value formal is *values — not shifted by self/name.
    obj_cid, name_cid, values_cid = pending.demand.operand_coordinate_cids
    assert name_cid is None
    assert obj_cid is not None
    assert values_cid is not None
    assert obj_cid != values_cid
    assert isinstance(pending.operands[1], StringValue)
    assert pending.operands[1].value == "field"
    assert pending.operands[0].term.name == "obj"
    assert pending.operands[2].term.name == "values"
    kinds = tuple(c.parameter_kind for c in function.sugar().formal_coordinates)
    names = tuple(c.declared_name for c in function.sugar().formal_coordinates)
    assert kinds == ("positional-or-keyword", "variadic-positional")
    assert names == ("obj", "values")
    # Exactly two formals — no phantom self or name formal.
    assert len(function.sugar().formal_coordinates) == 2
    formal_cids = {c.coordinate_cid for c in function.sugar().formal_coordinates}
    assert obj_cid in formal_cids and values_cid in formal_cids


def test_helper_kw_alone_undischarged_without_self_name_shift() -> None:
    function, pending = _helper(HELPER_KW)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setattr_named"
    obj_cid, name_cid, values_cid = pending.demand.operand_coordinate_cids
    assert name_cid is None
    assert pending.operands[1].value == "field"
    assert pending.operands[2].term.name == "values"
    kinds = tuple(c.parameter_kind for c in function.sugar().formal_coordinates)
    assert kinds == ("positional-or-keyword", "variadic-keyword")
    assert len(function.sugar().formal_coordinates) == 2


def test_helper_alone_is_not_completed_discrimination() -> None:
    _, pending = _helper(HELPER_STAR)
    with pytest.raises(AssertionError):
        assert isinstance(pending, Completed)


# ---------------------------------------------------------------------------
# *values / **values reach the declared stored value
# ---------------------------------------------------------------------------


def test_star_values_reach_declared_stored_value() -> None:
    helper, pending, receiver = _source_class_and_helper("    pass\n", HELPER_STAR)
    obj_cid, name_cid, values_cid = pending.demand.operand_coordinate_cids
    assert name_cid is None
    pack = TupleValue((TermValue(1), TermValue(2)))
    exits = pending.discharge({obj_cid: receiver, values_cid: pack})
    assert isinstance(exits, ExitSet)
    assert isinstance(exits.exits[0], Completed)
    stored = exits.exits[0].value
    record = getattr(stored, "record", None)
    assert record is not None
    assert any(
        isinstance(s, ObjectValue)
        and s.fields
        and s.fields[-1].name == "field"
        and s.fields[-1].value == pack
        for s in record.statements
    )
    del helper


def test_kw_values_reach_declared_stored_value() -> None:
    helper, pending, receiver = _source_class_and_helper("    pass\n", HELPER_KW)
    obj_cid, name_cid, values_cid = pending.demand.operand_coordinate_cids
    assert name_cid is None
    mapping = DictValue(((StringValue("a"), TermValue(1)),))
    exits = pending.discharge({obj_cid: receiver, values_cid: mapping})
    assert isinstance(exits.exits[0], Completed)
    record = exits.exits[0].value.record
    assert any(
        isinstance(s, ObjectValue)
        and s.fields
        and s.fields[-1].name == "field"
        and s.fields[-1].value == mapping
        for s in record.statements
    )
    del helper


def test_empty_star_stores_honest_empty_tuple() -> None:
    _, pending, receiver = _source_class_and_helper("    pass\n", HELPER_STAR)
    obj_cid, _, values_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge({obj_cid: receiver, values_cid: TupleValue(())})
    assert isinstance(exits.exits[0], Completed)
    record = exits.exits[0].value.record
    assert any(
        isinstance(s, ObjectValue)
        and s.fields
        and s.fields[-1].value == TupleValue(())
        for s in record.statements
    )


def test_bind_actuals_packs_star_without_self_name_shift() -> None:
    """SourceCallFrame.bind_actuals packs remaining positionals into *values.

    Frame parameters are exactly ``(obj, values)`` — no phantom self/name
    formal steals the pack slot (name is static StringValue on the mint).
    """
    from sugar_lift_py_tests.floor import ListValue

    tree = _tree(HELPER_STAR + "\nhelper([0], 1, 2, 3)\n")
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    frame = call.sugar().source_call_frame
    assert frame.parameters == ("obj", "values")
    assert frame.parameter_kinds == ("positional_or_keyword", "vararg")
    bound = frame.bind_actuals(
        (ListValue((TermValue(0),)), TermValue(1), TermValue(2), TermValue(3)),
        (),
    )
    assert bound.actuals == (
        ListValue((TermValue(0),)),
        TupleValue((TermValue(1), TermValue(2), TermValue(3))),
    )
    # Two bound slots only — pack is values, not shifted by self/name.
    assert len(bound) == 2


def test_bind_actuals_packs_kw_without_self_name_shift() -> None:
    """SourceCallFrame.bind_actuals packs extra keywords into **values."""
    from sugar_lift_py_tests.floor import ListValue

    tree = _tree(HELPER_KW + "\nhelper([0], a=1, b=2)\n")
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    frame = call.sugar().source_call_frame
    assert frame.parameters == ("obj", "values")
    assert frame.parameter_kinds == ("positional_or_keyword", "kwarg")
    bound = frame.bind_actuals(
        (ListValue((TermValue(0),)),),
        (("a", TermValue(1)), ("b", TermValue(2))),
    )
    assert bound.actuals == (
        ListValue((TermValue(0),)),
        DictValue(
            (
                (StringValue("a"), TermValue(1)),
                (StringValue("b"), TermValue(2)),
            )
        ),
    )
    assert len(bound) == 2


# ---------------------------------------------------------------------------
# Getter-only stays named AttributeError
# ---------------------------------------------------------------------------


def test_getter_only_property_named_attributeerror_with_star_pack() -> None:
    _, pending, receiver = _source_class_and_helper(
        "    @property\n" "    def field(self):\n" "        return 1\n",
        HELPER_STAR,
    )
    obj_cid, name_cid, values_cid = pending.demand.operand_coordinate_cids
    assert name_cid is None
    assert pending.pre_effect_state is not None
    exits = pending.discharge(
        {obj_cid: receiver, values_cid: TupleValue((TermValue(9),))}
    )
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert not isinstance(halted, Completed)
    assert halted.effect.exception_type_coordinate == _identity("AttributeError")
    assert halted.effect.occurrence_id is not None
    assert halted.state is not None
    assert pending.pre_effect_state.state is halted.state


def test_getter_only_discrimination_not_completed() -> None:
    _, pending, receiver = _source_class_and_helper(
        "    @property\n" "    def field(self):\n" "        return 1\n",
        HELPER_KW,
    )
    obj_cid, _, values_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: receiver,
            values_cid: DictValue(((StringValue("a"), TermValue(1)),)),
        }
    )
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Completed)


def test_no_self_name_shift_operand_order_discrimination() -> None:
    """Bite: name is static StringValue at slot 1; pack is value at slot 2."""
    _, pending = _helper(HELPER_STAR)
    assert isinstance(pending.operands[1], StringValue)
    assert pending.operands[1].value == "field"
    assert pending.operands[2].term.name == "values"
    # Must not look like (self, values, field) or (values, field, obj).
    with pytest.raises(AssertionError):
        assert pending.operands[0].term.name == "values"
    with pytest.raises(AssertionError):
        assert pending.demand.operand_coordinate_cids[1] is not None
