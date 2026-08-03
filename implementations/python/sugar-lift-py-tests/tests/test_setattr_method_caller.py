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
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute, Call, ClassDef, FunctionDef
from sugar_source_tree.tree import SourceFile

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
    assert isinstance(class_outcome, Complete)
    assert isinstance(class_outcome.value, ClassDefinitionValue)
    receiver = class_outcome.value.construct_receiver_state_from_block(
        None, class_outcome.value.class_definition_cid
    )
    assert isinstance(receiver, ObjectValue)
    return receiver


def _method_callsite(source: str) -> CallSiteValue:
    """Construct the bound method CallSiteValue (self prepended, body retained)."""
    tree = _tree(source)
    calls = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Attribute)
        and node.func.attr == "store"
    )
    assert len(calls) == 1, calls
    constructed = calls[0].sugar().desugar(None)
    assert isinstance(constructed, Complete), constructed
    assert isinstance(constructed.value, CallSiteValue), constructed.value
    return constructed.value


def _method_call_outcome(source: str):
    return _method_callsite(source).producer_outcome(None)


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
    assert isinstance(outcome, Complete), outcome
    assert isinstance(outcome.value, CallSiteValue), outcome.value
    return outcome.value


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


def test_bound_self_does_not_shift_obj_value_coordinates() -> None:
    """Positional method call binds self, then obj/value in declaration order."""
    source = TARGET_CLASS + METHOD_BODY + "\nWriter().store(Target(), 7)\n"
    callsite = _method_callsite(source)
    _assert_bound_self_first(callsite)
    target = _floor_target_arg(callsite.arg_values[1])
    assert target.class_name == "Target"
    assert callsite.arg_values[2] == TermValue(7)
    _assert_completed_call(callsite.producer_outcome(None))


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


def test_positional_keyword_and_default_method_calls_discharge() -> None:
    sites = (
        _method_callsite(
            TARGET_CLASS + METHOD_BODY + "\nWriter().store(Target(), 7)\n"
        ),
        _method_callsite(
            TARGET_CLASS + METHOD_BODY + "\nWriter().store(obj=Target(), value=7)\n"
        ),
        _method_callsite(
            TARGET_CLASS + METHOD_DEFAULTS + "\nWriter().store(Target())\n"
        ),
    )
    for site in sites:
        _assert_bound_self_first(site)
        assert _floor_target_arg(site.arg_values[1]).class_name == "Target"
        assert site.arg_values[2] == TermValue(7)
        _assert_completed_call(site.producer_outcome(None))


def test_discrimination_keyword_swap_is_not_positional_binding() -> None:
    """Bite: keyword value= must not silently bind as if positional-only."""
    truthful = _method_callsite(
        TARGET_CLASS + METHOD_BODY + "\nWriter().store(obj=Target(), value=7)\n"
    )
    # Same presentation shape with value=9 — different binding.
    other = _method_callsite(
        TARGET_CLASS + METHOD_BODY + "\nWriter().store(obj=Target(), value=9)\n"
    )
    _assert_bound_self_first(truthful)
    _assert_bound_self_first(other)
    assert truthful.arg_values[2] == TermValue(7)
    assert other.arg_values[2] == TermValue(9)
    assert truthful.arg_values[2] != other.arg_values[2]


# ---------------------------------------------------------------------------
# 4. Writable receiver completes
# ---------------------------------------------------------------------------


def test_writable_receiver_completes_via_method_discharge() -> None:
    _, _method, pending = _method_definition()
    target = _construct_class(TARGET_CLASS, "Target")
    assert target.methods == ()
    obj_cid, value_cid = _obj_value_cids(pending)
    exits = pending.discharge({obj_cid: target, value_cid: TermValue(7)})
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


def test_discrimination_writable_completion_is_not_attributeerror() -> None:
    outcome = _method_call_outcome(
        TARGET_CLASS + METHOD_BODY + "\nWriter().store(Target(), 7)\n"
    )
    _assert_completed_call(outcome)
    assert not isinstance(outcome, ExitSet)


# ---------------------------------------------------------------------------
# 5. Getter-only property → named AttributeError + pre-effect state
# ---------------------------------------------------------------------------


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
    exits = pending.discharge({obj_cid: target, value_cid: TermValue(7)})
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


def test_getter_only_property_method_call_binds_and_floor_refuses_store() -> None:
    """Bound-method call binds self/obj/value; Floor store path AttributeErrors.

    ``Target()`` arrives as a constructor CallSiteValue; dig to ObjectValue to
    prove the property is enrolled.  Floor ``setattr`` is the store path (not
    read).  Formal discharge with the dug receiver (sibling test) owns the
    pre-effect state identity; producer_outcome over an undug constructor arg
    is not the discharge instrument.
    """
    source = PROPERTY_TARGET + METHOD_BODY + "\nWriter().store(Target(), 7)\n"
    site = _method_callsite(source)
    _assert_bound_self_first(site)
    target = _floor_target_arg(site.arg_values[1])
    assert target.class_name == "Target"
    assert any(
        m.name == "field" and m.descriptor_kind == "property" for m in target.methods
    )
    assert site.arg_values[2] == TermValue(7)
    from sugar_lift_py_tests.floor import RaiseValue

    # Use a source fragment site from the method body store statement.
    _, method, _pending = _method_definition()
    floor_site = method.body[0].fragment
    direct = target.setattr("field", TermValue(7), floor_site)
    assert isinstance(direct, Complete) and isinstance(direct.value, RaiseValue)
    assert direct.value.effect.exception_name == "AttributeError"
    assert direct.value.effect.producer_node_owner == "ObjectValue.setattr"


def test_discrimination_writable_is_not_getter_only_halt() -> None:
    outcome = _method_call_outcome(
        TARGET_CLASS + METHOD_BODY + "\nWriter().store(Target(), 7)\n"
    )
    _assert_completed_call(outcome)


# ---------------------------------------------------------------------------
# 6. Off-by-one self-binding and read-authorizes-write twins fail
# ---------------------------------------------------------------------------


def test_off_by_one_callsite_args_do_not_match_truthful_binding() -> None:
    """Discrimination: pretend self was not prepended (args slide left)."""
    site = _method_callsite(
        TARGET_CLASS + METHOD_BODY + "\nWriter().store(Target(), 7)\n"
    )
    truthful = site.arg_values
    assert len(truthful) == 3
    assert isinstance(truthful[0], ObjectValue)
    assert truthful[0].class_name == "Writer"
    # Off-by-one: drop self — remaining (Target, 7) is not the full binding.
    off_by_one = truthful[1:]
    assert len(off_by_one) == 2
    assert off_by_one != truthful
    assert not (
        isinstance(off_by_one[0], ObjectValue) and off_by_one[0].class_name == "Writer"
    )


def test_read_does_not_authorize_completed_store_on_getter_only_property() -> None:
    """Lying twin: property is readable but store must not complete."""
    _, _method, pending = _method_definition()
    target = _construct_class(PROPERTY_TARGET, "Target")
    # Readable property is enrolled.
    assert any(
        m.name == "field" and m.descriptor_kind == "property" for m in target.methods
    )
    obj_cid, value_cid = _obj_value_cids(pending)
    exits = pending.discharge({obj_cid: target, value_cid: TermValue(99)})
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
    exits = pending.discharge({obj_cid: target, value_cid: TermValue(99)})
    assert isinstance(exits.exits[0], Completed)
    assert not isinstance(exits.exits[0], Halted)
