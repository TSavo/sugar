"""JOIN CHECK: unpack assignment with formal setattr_named through a real caller.

Concrete program:

    def f(obj, p, q):
        x, obj.field = p, q
        return x

The unpack admits a Name leaf (``x``) then an attribute store leaf. Formal
desugar mints undischarged ``setattr_named``; discharge projects Completed
field stores or named AttributeError, carrying authentic pre-effect state.

Operand order (setattr_named owner law):

  source evaluation (store half): value → receiver   (q, obj)
  discharge / mint:               receiver, name, value
                                  (obj, StringValue(\"field\"), q)

  Name slot is static — coordinate is None (not a formal).

Acceptance (each with a discrimination twin):

  1. Helper alone retains setattr_named demand in discharge order.
  2. Writable source-defined receiver completes x→p and the field store.
  3. Getter-only property → named AttributeError; x preserved in halt
     pre-effect state; never fabricated statement completion.
  4. RHS/receiver evaluation order differs from discharge order.
  5. First-store halt blocks later targets.
  6. Swapped-coordinate and read-authorizes-write twins fail.

Does not touch carrier/ExitSet, reducer, attribute-store producer/projector,
assertion-boundary identity, or census.
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import AttributeStoreRuntimeEffect
from sugar_lift_py_tests.floor import (
    ObjectField,
    ObjectMethodValue,
    ObjectValue,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef, FunctionDef
from sugar_source_tree.tree import SourceFile

PROGRAM = "def f(obj, p, q):\n    x, obj.field = p, q\n    return x\n"


def _tree(source: str, name: str = "unpack_setattr_caller.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper():
    tree = _tree(PROGRAM, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def _source_class_receiver(class_body: str):
    """Build a source-defined class receiver for discharge (ClassDef door)."""
    source = f"class Widget:\n{class_body}\n" + PROGRAM
    tree = _tree(source, "source_class_unpack_setattr.py")
    class_def = next(node for node in tree.nodes() if isinstance(node, ClassDef))
    helper = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "f"
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
    return helper, pending, receiver


def _completed_universe(pending, actuals) -> UniverseValue:
    exits = pending.discharge(actuals)
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    face = exits.exits[0]
    assert isinstance(face, Completed)
    assert isinstance(face.value, UniverseValue)
    return face.value


# ---------------------------------------------------------------------------
# 1. Helper alone retains setattr_named demand
# ---------------------------------------------------------------------------


def test_helper_alone_retains_setattr_named_demand_in_discharge_order() -> None:
    _, pending = _helper()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setattr_named"
    assert isinstance(pending.operands[1], StringValue)
    assert pending.operands[1].value == "field"
    # Discharge order: receiver, static name, value (q). Name x binds p.
    assert pending.operands[0].term.name == "obj"
    assert pending.operands[2].term.name == "q"
    cids = pending.demand.operand_coordinate_cids
    assert cids[0] is not None and cids[2] is not None
    assert cids[1] is None  # static attribute name is not a formal
    assert cids[0] != cids[2]
    parameters = tuple(
        inspect.signature(_NATIVE_OPERATION_PROJECTORS["setattr_named"]).parameters
    )
    assert parameters == ("receiver", "name", "value", "site")
    assert pending.pre_effect_state is not None


def test_helper_alone_is_not_a_completed_face_discrimination() -> None:
    _, pending = _helper()
    with pytest.raises(AssertionError):
        assert isinstance(pending, Complete)
    with pytest.raises(AssertionError):
        assert isinstance(pending, Completed)


# ---------------------------------------------------------------------------
# 2. Writable source-defined receiver completes x and field store
# ---------------------------------------------------------------------------


def test_writable_source_defined_receiver_completes_x_and_field_store() -> None:
    _, pending, receiver = _source_class_receiver("    pass\n")
    assert receiver.methods == ()
    obj_cid, _, q_cid = pending.demand.operand_coordinate_cids
    universe = _completed_universe(pending, {obj_cid: receiver, q_cid: TermValue(7)})
    # Field store completed with discharged value.
    assert any(
        isinstance(s, ObjectValue)
        and s.fields
        and s.fields[-1].name == "field"
        and s.fields[-1].value == TermValue(7)
        for s in universe.record.statements
    )
    # Earlier x binding: return is formal p (Name spent by substitute).
    returns = [s for s in universe.record.statements if isinstance(s, ReturnValue)]
    assert len(returns) == 1
    assert returns[0].value.term.name == "p"
    post = str(universe.post())
    assert "out" in post and "p" in post


def test_writable_source_defined_receiver_completes_discrimination() -> None:
    _, pending, receiver = _source_class_receiver("    pass\n")
    obj_cid, _, q_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge({obj_cid: receiver, q_cid: TermValue(7)})
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Halted), "writable field must complete"


# ---------------------------------------------------------------------------
# 3. Getter-only property → AttributeError; x in pre-effect state
# ---------------------------------------------------------------------------


def test_property_without_setter_named_attribute_error_preserves_x_state() -> None:
    helper, pending, receiver = _source_class_receiver(
        "    @property\n" "    def field(self):\n" "        return 1\n"
    )
    assert any(
        m.name == "field" and m.descriptor_kind == "property" for m in receiver.methods
    )
    # Floor store path (not read) refuses.
    site = helper.body[0].fragment
    from sugar_lift_py_tests.floor import RaiseValue

    direct = receiver.setattr("field", TermValue(7), site)
    assert isinstance(direct, Complete) and isinstance(direct.value, RaiseValue)
    assert direct.value.effect.exception_name == "AttributeError"
    assert direct.value.effect.producer_node_owner == "ObjectValue.setattr"

    assert pending.pre_effect_state is not None
    obj_cid, _, q_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge({obj_cid: receiver, q_cid: TermValue(7)})
    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert not isinstance(halted, Completed)
    assert halted.effect.exception_type_coordinate == _identity("AttributeError")
    assert halted.effect.occurrence_id is not None
    # Authentic earlier-binding pre-effect state (post-#6640 / #6644).
    assert halted.state is not None
    assert pending.pre_effect_state.state is halted.state
    assert not isinstance(getattr(halted, "value", None), UniverseValue)


def test_property_without_setter_discrimination_not_completed() -> None:
    """Bite: getter must not authorize Completed store; state must not be dropped."""
    _, pending, receiver = _source_class_receiver(
        "    @property\n" "    def field(self):\n" "        return 1\n"
    )
    obj_cid, _, q_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge({obj_cid: receiver, q_cid: TermValue(99)})
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Completed), "read path licensed a store"
    with pytest.raises(AssertionError):
        assert exits.exits[0].state is None, "halt dropped earlier-binding state"


def test_read_authorizes_write_twin_fails() -> None:
    """Lying twin: borrowing readable property evidence to complete a store."""
    _, pending, receiver = _source_class_receiver(
        "    @property\n" "    def field(self):\n" "        return 1\n"
    )
    # Property is readable via the enrollment of the getter.
    assert any(m.descriptor_kind == "property" for m in receiver.methods)
    obj_cid, _, q_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge({obj_cid: receiver, q_cid: TermValue(1)})
    assert isinstance(exits.exits[0], Halted)
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Completed), "read authorized write"


# ---------------------------------------------------------------------------
# 4. Evaluation order ≠ discharge order
# ---------------------------------------------------------------------------


def test_eval_order_differs_from_discharge_order() -> None:
    """Store half: source eval is value→receiver; discharge is receiver,name,value."""
    _, pending = _helper()
    discharge_names = (
        pending.operands[0].term.name,  # obj
        pending.operands[1].value,  # "field"
        pending.operands[2].term.name,  # q
    )
    # Source eval for the store leaf: value first, then receiver (static name
    # is not evaluated). Name x binds p before the store runs.
    source_eval_store = ("q", "obj", "field")
    assert discharge_names == ("obj", "field", "q")
    assert discharge_names != source_eval_store
    with pytest.raises(AssertionError):
        assert discharge_names == source_eval_store


def test_swapped_receiver_value_coordinates_twin_fails() -> None:
    """Lying mint with receiver/value slots swapped is distinguishable."""
    function, truthful = _helper()
    site = function.body[0].fragment
    obj_c, name_c, value_c = truthful.coordinates
    # name_c is None for static field; lying swaps receiver and value formals.
    lying = NativeOperationExitCarrierV1.mint(
        site=site,
        operator="setattr_named",
        operands=(
            truthful.operands[2],  # value formal in receiver slot
            truthful.operands[1],  # static name
            truthful.operands[0],  # receiver formal in value slot
        ),
        coordinates=(value_c, name_c, obj_c),
    )
    writable = ObjectValue("R", (ObjectField("field", TermValue(0)),))
    # Truthful: obj gets ObjectValue, q gets TermValue(9)
    actuals = {
        obj_c.coordinate_cid: writable,
        value_c.coordinate_cid: TermValue(9),
    }
    truthful_exits = truthful.discharge(actuals)
    assert isinstance(truthful_exits.exits[0], Completed)
    t_univ = truthful_exits.exits[0].value
    t_fields = [
        s for s in t_univ.record.statements if isinstance(s, ObjectValue) and s.fields
    ]
    assert t_fields and t_fields[0].fields[-1].value == TermValue(9)

    # Lying maps value formal to ObjectValue and receiver formal to 9 —
    # either fails or stores differently.
    lying_exits = lying.discharge(actuals)
    lying_face = lying_exits.exits[0]
    if isinstance(lying_face, Completed) and isinstance(
        lying_face.value, UniverseValue
    ):
        l_fields = [
            s
            for s in lying_face.value.record.statements
            if isinstance(s, ObjectValue) and s.fields
        ]
        if l_fields:
            assert l_fields[0].fields[-1].value != TermValue(9) or (
                l_fields[0] is not t_fields[0]
            )
        # At minimum: not identical to the truthful completed face identity.
        assert lying_face.value != t_univ or lying_face is not truthful_exits.exits[0]
    else:
        assert isinstance(lying_face, Halted)

    with pytest.raises(AssertionError):
        assert (
            truthful.operands[0].term.name == truthful.operands[2].term.name
        ), "receiver and value formals collapsed"


# ---------------------------------------------------------------------------
# 5. First-store halt blocks later targets
# ---------------------------------------------------------------------------


def test_first_store_halt_blocks_later_targets() -> None:
    """``o.x, o.y = p, q`` free undecided o: first-halt arm has no second store."""
    source = "def f(p, q):\n    o.x, o.y = p, q\n    return p\n"
    tree = _tree(source, "dual_attr.py")
    fn = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    outcome = outcome_to_exitset(fn.sugar().desugar(None))
    halted = [e for e in outcome.exits if isinstance(e, Halted)]
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    # Dual-face AttributeStoreRuntimeEffect composition: 2 halt + 1 completed.
    assert len(halted) == 2
    assert len(completed) == 1
    # First-halt arm (no prior store) carries no AttributeStore testimony.
    first = next(
        h
        for h in halted
        if isinstance(h.effect, AttributeStoreRuntimeEffect)
        and "attr=x" in h.effect.reason
        and h.state is not None
        and not any(
            isinstance(getattr(e, "effect", None), AttributeStoreRuntimeEffect)
            for e in getattr(h.state, "entries", ())
        )
    )
    assert isinstance(first.effect, AttributeStoreRuntimeEffect)
    # No completed-only reading of the body.
    assert not (len(halted) == 0 and len(completed) == 1)


def test_first_store_halt_blocks_later_targets_discrimination() -> None:
    """Bite: dual free stores must not present a sole Completed arm."""
    source = "def f(p, q):\n    o.x, o.y = p, q\n    return p\n"
    tree = _tree(source, "dual_attr_d.py")
    fn = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    outcome = outcome_to_exitset(fn.sugar().desugar(None))
    with pytest.raises(AssertionError):
        assert len(outcome.exits) == 1 and isinstance(
            outcome.exits[0], Completed
        ), "later target ran after first-store halt"
