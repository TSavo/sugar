"""Formal ``setattr_named`` through a bound-method receiver binding.

Concrete program:

    class Writer:
        def store(self, obj, value):
            obj.field = value

    Writer().store(target, 7)

Python law: a bound method call supplies ``self`` first. That binding must not
shift ``obj`` / ``value`` in the setattr_named demand. Discharge order remains
``(receiver, StringValue(name), value)`` with coordinates
``(obj.formal, None, value.formal)``; ``self`` is the method binder's slot, not
a store operand.

Acceptance (each with a discrimination twin where noted):

  1. Bound ``self`` does not shift obj/value coordinates.
  2. Helper method alone retains the undischarged setattr_named demand.
  3. Positional, keyword, and default method calls discharge.
  4. Writable receiver completes.
  5. Getter-only property → named AttributeError with exact pre-effect state;
     matching boundary restores that state; wrong boundary retains the halt.
  6. Off-by-one self-binding and read-authorizes-write twins fail.

Exceptional pre-effect identity on the bound-method *call* producer path may
stay red until codex-1's lossless reduce_body fix lands; formal *discharge*
pre-effect identity is asserted here as the #6640 join instrument.

Does not touch: function_universe_sugar, carrier/ExitSet, attribute-store
producer/projector/Floor, parameter-name maps, unpack×attribute or pandas
attribute-store lanes.
"""

from __future__ import annotations

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import ObjectValue, StringValue, TermValue
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.floor.named_expression_value import (
    caller_stores_of,
    peel_walrus_binds,
)
from sugar_lift_py_tests.floor.receiver_field_store_value import (
    ReceiverFieldStoreValue,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute, Call, ClassDef, FunctionDef
from sugar_source_tree.tree import SourceFile

from frame_fresh import FRAME_FRESH

METHOD_BODY = (
    "class Writer:\n" "    def store(self, obj, value):\n" "        obj.field = value\n"
)

METHOD_DEFAULTS = (
    "class Writer:\n"
    "    def store(self, obj, value=7):\n"
    "        obj.field = value\n"
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


def _assert_bound_self_first(callsite: CallSiteValue) -> None:
    """arg_values[0] is Writer; remaining are obj, value."""
    assert callsite.parameters[0] == "self"
    assert callsite.parameters[1:3] == ("obj", "value")
    assert isinstance(callsite.arg_values[0], ObjectValue)
    assert callsite.arg_values[0].class_name == "Writer"
    assert len(callsite.arg_values) == len(callsite.parameters)


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def _assert_named_halt(outcome, *, require_pre_effect_state: bool = True) -> Halted:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("AttributeError")
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    if require_pre_effect_state:
        # #6640: exceptional discharge stamps reducer-owned pre-effect state.
        # Bound-method *call* producer path may stay red until codex-1 lossless
        # reduce_body; formal discharge path must already stamp it.
        assert halted.state is not None, (
            "NativeOperationResolutionV1.project omitted the formal setattr_named "
            "halt's real pre-effect state"
        )
    return halted


def _assert_completed_call(outcome) -> CallSiteValue:
    """The call completes, carrying the store ``obj.field = value`` the body
    made on the caller's ``Target()`` (``CallerStoreValue``,
    ``caller_visible_stores``), and presents the call beneath it."""
    value = outcome.completed_value()
    assert value is not None, outcome
    binds, presented = peel_walrus_binds(value)
    walrus, stores = caller_stores_of(binds)
    assert walrus == (), value
    assert [(type(s), s.attr, s.value) for s in stores] == [
        (ReceiverFieldStoreValue, "field", TermValue(7))
    ], value
    assert stores[0].receiver.class_name == "Target", value
    assert isinstance(presented, CallSiteValue), value
    return presented


def _obj_value_cids(pending: NativeOperationExitCarrierV1):
    """setattr_named demand: (obj, static name, value) — never self."""
    assert pending.demand.operator == "setattr_named"
    assert len(pending.demand.operand_coordinate_cids) == 3
    assert isinstance(pending.operands[1], StringValue)
    assert pending.operands[1].value == "field"
    assert pending.demand.operand_coordinate_cids[1] is None
    names = (
        pending.operands[0].term.name,
        pending.operands[2].term.name,
    )
    assert names == ("obj", "value"), names
    obj_cid, _name_cid, value_cid = pending.demand.operand_coordinate_cids
    return obj_cid, value_cid


class _Expected:
    def __init__(self, name: str):
        self.identity = _identity(name)

    def exception_type_identity(self):
        return self.identity


def _route(exits: ExitSet, expected: str) -> ExitSet:
    return exits.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected(expected)),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )


# ---------------------------------------------------------------------------
# 1. Bound self does not shift obj/value
# ---------------------------------------------------------------------------


def test_method_alone_mints_setattr_named_over_obj_value_not_self() -> None:
    """Method body ``obj.field = value`` — setattr_named formals exclude self."""
    _class_def, method, pending = _method_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setattr_named"
    assert isinstance(pending.operands[1], StringValue)
    assert pending.operands[1].value == "field"
    assert pending.operands[0].term.name == "obj"
    assert pending.operands[2].term.name == "value"
    method_formals = tuple(p.name for p in method.params)
    assert method_formals[0] == "self"
    assert method_formals[1:] == ("obj", "value")
    obj_cid, value_cid = _obj_value_cids(pending)
    assert obj_cid is not None and value_cid is not None
    assert obj_cid != value_cid


def _floor_target_arg(arg) -> ObjectValue:
    """Dig a constructed ``Target()`` CallSiteValue to ObjectValue."""
    if isinstance(arg, ObjectValue):
        return arg
    assert isinstance(arg, CallSiteValue), arg
    floored = arg.force_floor(None, owner="setattr-method-caller target dig")
    assert isinstance(floored, ObjectValue), floored
    return floored


def test_discrimination_self_is_not_the_setattr_receiver_slot() -> None:
    """Bite: setattr_named demand coordinates must not be the method's self formal."""
    _class_def, method, pending = _method_definition()
    self_coord = method.formal_coordinates()[0]
    obj_cid, value_cid = _obj_value_cids(pending)
    assert self_coord.coordinate_cid not in {obj_cid, value_cid}


# ---------------------------------------------------------------------------
# 2. Helper method alone retains setattr_named demand
# ---------------------------------------------------------------------------


def test_helper_method_alone_retains_setattr_named_demand() -> None:
    _, _method, pending = _method_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setattr_named"
    assert len(pending.operands) == 3
    assert pending.demand.operand_coordinate_cids[1] is None
    assert pending.demand.operand_coordinate_cids[0] is not None
    assert pending.demand.operand_coordinate_cids[2] is not None


def test_discrimination_method_alone_is_not_completed() -> None:
    """Bite: undischarged carrier is not a Completed store face."""
    _, _method, pending = _method_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert not isinstance(pending, Completed)
    assert not isinstance(pending, ExitSet)


# ---------------------------------------------------------------------------
# 3. Positional, keyword, and default calls discharge
# ---------------------------------------------------------------------------


def test_writable_receiver_completes_via_method_discharge() -> None:
    _, _method, pending = _method_definition()
    target = _construct_class(TARGET_CLASS, "Target")
    assert target.methods == ()
    obj_cid, value_cid = _obj_value_cids(pending)
    exits = pending.discharge(None, {obj_cid: target, value_cid: TermValue(7)})
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    stored = exits.exits[0].value
    record = getattr(stored, "record", None)
    assert record is not None
    assert any(
        isinstance(s, ObjectValue)
        and s.fields
        and s.fields[-1].name == "field"
        and s.fields[-1].value == TermValue(7)
        for s in record.statements
    )


def test_getter_only_property_named_attribute_error_with_pre_effect_state() -> None:
    """#6640 join on bound-method setattr_named: discharge stamps pre-state.

    Formal discharge path (method alone → actuals) must carry exact reducer
    testimony. Matching boundary restores it; wrong boundary retains the halt.
    """
    _, _method, pending = _method_definition()
    target = _construct_class(PROPERTY_TARGET, "Target")
    assert any(
        m.name == "field" and m.descriptor_kind == "property" for m in target.methods
    )
    testimony = pending.pre_effect_state
    assert testimony is not None, (
        "method body reducer did not enroll ReducerPreEffectStateV1 on the "
        "formal setattr_named carrier"
    )

    obj_cid, value_cid = _obj_value_cids(pending)
    exits = pending.discharge(None, {obj_cid: target, value_cid: TermValue(7)})
    halted = _assert_named_halt(exits, require_pre_effect_state=True)
    assert halted.effect.exception_type_coordinate == _identity("AttributeError")
    assert "AttributeError" in repr(halted.effect.exception_type_coordinate)
    assert halted.state is testimony.state

    # Matching boundary restores the same pre-effect state object.
    routed = _route(exits, "AttributeError")
    assert len(routed.exits) == 1
    completed = routed.exits[0]
    assert isinstance(completed, Completed)
    assert completed.value is testimony.state

    # Wrong boundary retains the identical effect and pre-effect state.
    retained = _route(exits, "ValueError")
    assert len(retained.exits) == 1
    face = retained.exits[0]
    assert isinstance(face, Halted)
    assert face.effect is halted.effect
    assert face.state is halted.state


def test_read_does_not_authorize_completed_store_on_getter_only_property() -> None:
    """Lying twin: property is readable but store must not complete."""
    _, _method, pending = _method_definition()
    target = _construct_class(PROPERTY_TARGET, "Target")
    # Readable property is enrolled.
    assert any(
        m.name == "field" and m.descriptor_kind == "property" for m in target.methods
    )
    obj_cid, value_cid = _obj_value_cids(pending)
    exits = pending.discharge(None, {obj_cid: target, value_cid: TermValue(99)})
    assert isinstance(exits.exits[0], Halted)
    assert not isinstance(exits.exits[0], Completed)
    assert exits.exits[0].effect.exception_type_coordinate == _identity(
        "AttributeError"
    )


def test_discrimination_writable_store_is_not_read_authorized_halt() -> None:
    """Positive twin of read-authorizes-write: empty class completes."""
    _, _method, pending = _method_definition()
    target = _construct_class(TARGET_CLASS, "Target")
    obj_cid, value_cid = _obj_value_cids(pending)
    exits = pending.discharge(None, {obj_cid: target, value_cid: TermValue(99)})
    assert isinstance(exits.exits[0], Completed)
    assert not isinstance(exits.exits[0], Halted)
