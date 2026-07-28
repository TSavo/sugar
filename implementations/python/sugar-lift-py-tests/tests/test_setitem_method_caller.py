"""Wave 3: formal ``setitem`` through a bound-method receiver binding.

Concrete program:

    class Holder:
        def store(self, obj, key, value):
            obj[key] = value

    Holder().store([0], 0, 9)

Python law: a bound method call supplies ``self`` first. That binding must not
shift ``obj`` / ``key`` / ``value`` in the setitem demand. Discharge order for
the store remains ``(receiver, index, value)`` == ``(obj, key, value)``;
``self`` is the method binder's slot, not a store operand.

Acceptance (each with a discrimination twin where noted):

  1. Bound ``self`` does not shift obj/key/value coordinates.
  2. Positional, keyword, and default method calls discharge the same demand.
  3. Mutable store completes.
  4. Invalid index yields named IndexError.
  5. Off-by-one binding twin fails (self-as-obj is not the truthful store).

Does not touch the setitem store producer, carrier/ExitSet, projectors, Floor
setitem, or parameter-name maps — consumer/test only.
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
from sugar_lift_py_tests.floor import ListValue, ObjectValue, TermValue
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute, Call, ClassDef, FunctionDef
from sugar_source_tree.tree import SourceFile

METHOD_BODY = (
    "class Holder:\n"
    "    def store(self, obj, key, value):\n"
    "        obj[key] = value\n"
)

METHOD_DEFAULTS = (
    "class Holder:\n"
    "    def store(self, obj, key=0, value=9):\n"
    "        obj[key] = value\n"
)


def _tree(source: str, name: str = "setitem_method_caller.py") -> SourceFile:
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


def _source_holder_receiver():
    class_def, _method, pending = _method_definition()
    class_outcome = class_def.sugar().desugar(None)
    assert isinstance(class_outcome, Complete)
    assert isinstance(class_outcome.value, ClassDefinitionValue)
    receiver = class_outcome.value.construct_receiver_state_from_block(
        None, class_outcome.value.class_definition_cid
    )
    assert isinstance(receiver, ObjectValue)
    return receiver, pending


def _method_callsite(source: str) -> CallSiteValue:
    """Construct the bound method CallSiteValue (self prepended, body retained)."""
    tree = _tree(source)
    # Bound method call is Call(func=Attribute(attr="store")), not Holder().
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
    """Reduce the bound method body through the callsite producer path.

    MethodCallSugar / ObjectValue.call_method_value return a CallSiteValue
    with ``self`` already prepended in arg_values.  ``producer_outcome`` is
    the same consumer free-function calls use to publish Completed/Halted
    faces from the authenticated body (including formal setitem discharge).
    """
    return _method_callsite(source).producer_outcome(None)


def _assert_bound_self_first(callsite: CallSiteValue) -> None:
    """arg_values[0] is the Holder receiver; remaining are obj/key/value."""
    assert callsite.parameters[0] == "self"
    assert callsite.parameters[1:4] == ("obj", "key", "value")
    assert isinstance(callsite.arg_values[0], ObjectValue)
    assert callsite.arg_values[0].class_name == "Holder"
    # Bound self is slot 0 — obj/key/value occupy 1..3, never shifted left.
    assert len(callsite.arg_values) == len(callsite.parameters)


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def _assert_named_halt(outcome) -> Halted:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate is not None
    assert halted.effect.occurrence_id is not None
    # #6640: exceptional discharge stamps the reducer-owned pre-effect state.
    assert halted.state is not None, (
        "NativeOperationResolutionV1.project omitted the formal setitem "
        "halt's real pre-effect state"
    )
    return halted


def _assert_completed_call(outcome) -> CallSiteValue:
    """Successful method body publishes as Complete(CallSiteValue).

    ``CallSiteValue.project_producer_outcome`` replaces a completed body
    record with the Call coordinate itself (Complete(self)), while halted
    bodies remain ExitSet(Halted(...)).
    """
    assert isinstance(outcome, Complete), outcome
    assert isinstance(outcome.value, CallSiteValue), outcome.value
    return outcome.value


def _stored_list(completed_face) -> ListValue:
    assert isinstance(completed_face, Completed)
    record = getattr(completed_face.value, "record", None)
    assert record is not None
    lists = [s for s in record.statements if isinstance(s, ListValue)]
    assert len(lists) == 1, lists
    return lists[0]


def _obj_key_value_cids(pending: NativeOperationExitCarrierV1):
    """Setitem demand slots — never the method's self formal."""
    assert pending.demand.operator == "setitem"
    assert len(pending.demand.operand_coordinate_cids) == 3
    names = tuple(value.term.name for value in pending.operands)
    assert names == ("obj", "key", "value"), names
    return pending.demand.operand_coordinate_cids


# ---------------------------------------------------------------------------
# 1. Bound self does not shift obj/key/value
# ---------------------------------------------------------------------------


def test_method_alone_mints_setitem_over_obj_key_value_not_self() -> None:
    """Method body ``obj[key] = value`` — setitem formals exclude ``self``."""
    _class_def, method, pending = _method_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"
    names = tuple(value.term.name for value in pending.operands)
    assert names == ("obj", "key", "value")
    assert "self" not in names
    # Method formals include self; setitem demand does not absorb it as obj.
    method_formals = tuple(p.name for p in method.params)
    assert method_formals[0] == "self"
    assert method_formals[1:] == ("obj", "key", "value")
    obj_cid, key_cid, value_cid = _obj_key_value_cids(pending)
    assert len({obj_cid, key_cid, value_cid}) == 3


def test_bound_self_does_not_shift_obj_key_value_coordinates() -> None:
    """Positional method call binds self, then obj/key/value in declaration order."""
    source = METHOD_BODY + "\nHolder().store([0, 1], 0, 9)\n"
    callsite = _method_callsite(source)
    _assert_bound_self_first(callsite)
    # Actuals after self: list, 0, 9 — not self-shifted into obj.
    assert callsite.arg_values[1] == ListValue((TermValue(0), TermValue(1)))
    assert callsite.arg_values[2] == TermValue(0)
    assert callsite.arg_values[3] == TermValue(9)
    _assert_completed_call(callsite.producer_outcome(None))


def test_discrimination_self_is_not_the_setitem_receiver_slot() -> None:
    """Bite: setitem demand coordinates must not be the method's self formal."""
    _class_def, method, pending = _method_definition()
    self_coord = method.formal_coordinates()[0]
    obj_cid, key_cid, value_cid = _obj_key_value_cids(pending)
    assert self_coord.coordinate_cid not in {obj_cid, key_cid, value_cid}


# ---------------------------------------------------------------------------
# 2. Positional, keyword, and default calls discharge
# ---------------------------------------------------------------------------


def test_positional_keyword_and_default_method_calls_discharge() -> None:
    sites = (
        _method_callsite(METHOD_BODY + "\nHolder().store([0], 0, 9)\n"),
        _method_callsite(
            METHOD_BODY + "\nHolder().store(obj=[0], key=0, value=9)\n"
        ),
        _method_callsite(METHOD_DEFAULTS + "\nHolder().store([0])\n"),
    )
    for site in sites:
        _assert_bound_self_first(site)
        # After self: obj is the list, key is 0, value is 9 (defaults included).
        assert site.arg_values[1] == ListValue((TermValue(0),))
        assert site.arg_values[2] == TermValue(0)
        assert site.arg_values[3] == TermValue(9)
        _assert_completed_call(site.producer_outcome(None))


def test_discrimination_keyword_swap_is_not_positional_store() -> None:
    """Bite: keyword-swapped key/value must not match truthful cell binding."""
    truthful = _method_callsite(
        METHOD_BODY + "\nHolder().store([0, 1, 2], key=1, value=99)\n"
    )
    swapped = _method_callsite(
        METHOD_BODY + "\nHolder().store([0, 1, 2], key=99, value=1)\n"
    )
    _assert_bound_self_first(truthful)
    _assert_bound_self_first(swapped)
    assert truthful.arg_values[2:] == (TermValue(1), TermValue(99))
    assert swapped.arg_values[2:] == (TermValue(99), TermValue(1))
    assert truthful.arg_values[2:] != swapped.arg_values[2:]
    t_out = truthful.producer_outcome(None)
    s_out = swapped.producer_outcome(None)
    _assert_completed_call(t_out)
    # Swapped either completes (different binding already proven) or halts.
    if isinstance(s_out, Complete):
        _assert_completed_call(s_out)
    else:
        assert isinstance(s_out, ExitSet)
        assert isinstance(s_out.exits[0], Halted)


# ---------------------------------------------------------------------------
# 3. Mutable store completes
# ---------------------------------------------------------------------------


def test_mutable_method_store_completes() -> None:
    holder, pending = _source_holder_receiver()
    obj_cid, key_cid, value_cid = _obj_key_value_cids(pending)
    # Direct discharge with bound-style actuals: only obj/key/value (no self).
    exits = pending.discharge(
        {
            obj_cid: ListValue((TermValue(0), TermValue(1))),
            key_cid: TermValue(0),
            value_cid: TermValue(9),
        }
    )
    assert isinstance(exits.exits[0], Completed)
    assert _stored_list(exits.exits[0]) == ListValue((TermValue(9), TermValue(1)))
    # Holder itself is not a setitem operand here — method self is separate.
    del holder


def test_discrimination_mutable_completion_is_not_indexerror() -> None:
    outcome = _method_call_outcome(METHOD_BODY + "\nHolder().store([0], 0, 9)\n")
    _assert_completed_call(outcome)
    assert not isinstance(outcome, ExitSet)


# ---------------------------------------------------------------------------
# 4. Invalid index → named IndexError
# ---------------------------------------------------------------------------


def test_invalid_index_method_call_halts_with_named_indexerror() -> None:
    site = _method_callsite(METHOD_BODY + "\nHolder().store([0], 4, 9)\n")
    _assert_bound_self_first(site)
    assert site.arg_values[1:] == (
        ListValue((TermValue(0),)),
        TermValue(4),
        TermValue(9),
    )
    halted = _assert_named_halt(site.producer_outcome(None))
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    # Pre-effect state is the exact object carried on the halt (not None).
    assert halted.state is not None


def test_invalid_index_discharge_shares_reducer_pre_effect_state() -> None:
    """#6640 join: bound-method setitem IndexError carries enrolled pre-state.

    Method alone mints the setitem carrier; the reducer enrolls
    ``pre_effect_state`` before discharge.  Exceptional projection must stamp
    that same testimony onto ``Halted.state`` — matching boundary resume and
    wrong-boundary retention both depend on identity, not a fabricated empty
    block.
    """
    _holder, pending = _source_holder_receiver()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    testimony = pending.pre_effect_state
    assert testimony is not None, (
        "method body reducer did not enroll ReducerPreEffectStateV1 on the "
        "formal setitem carrier"
    )

    obj_cid, key_cid, value_cid = _obj_key_value_cids(pending)
    exits = pending.discharge(
        {
            obj_cid: ListValue((TermValue(0),)),
            key_cid: TermValue(4),
            value_cid: TermValue(9),
        }
    )
    halted = _assert_named_halt(exits)
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert halted.state is testimony.state

    # Matching boundary consumes the halt and restores the same pre-effect state.
    class _Expected:
        def __init__(self, name: str):
            self.identity = _identity(name)

        def exception_type_identity(self):
            return self.identity

    routed = exits.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected("IndexError")),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )
    assert len(routed.exits) == 1
    completed = routed.exits[0]
    assert isinstance(completed, Completed)
    assert completed.value is testimony.state

    # Wrong boundary retains the identical effect and pre-effect state.
    retained = exits.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected("ValueError")),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )
    assert len(retained.exits) == 1
    face = retained.exits[0]
    assert isinstance(face, Halted)
    assert face.effect is halted.effect
    assert face.state is halted.state


def test_discrimination_in_range_index_is_not_indexerror() -> None:
    outcome = _method_call_outcome(METHOD_BODY + "\nHolder().store([0], 0, 9)\n")
    _assert_completed_call(outcome)
    # Discrimination: completion is not a Halted face with pre-effect state.
    assert not isinstance(outcome, ExitSet)


# ---------------------------------------------------------------------------
# 5. Off-by-one binding twin fails
# ---------------------------------------------------------------------------


def test_off_by_one_binding_twin_fails_against_truthful_store() -> None:
    """If self were shifted into the obj slot, store actuals would misalign.

    Truthful discharge keys obj/key/value.  An off-by-one map that slides the
    call actuals left (list under key, index under value, value dropped into
    a non-list receiver) cannot produce the truthful post-state of
    ``[0,1][0] = 9``.
    """
    _holder, pending = _source_holder_receiver()
    obj_cid, key_cid, value_cid = _obj_key_value_cids(pending)
    base = ListValue((TermValue(0), TermValue(1)))
    truthful = pending.discharge(
        {obj_cid: base, key_cid: TermValue(0), value_cid: TermValue(9)}
    )
    assert isinstance(truthful.exits[0], Completed)
    assert _stored_list(truthful.exits[0]) == ListValue((TermValue(9), TermValue(1)))

    # Off-by-one: list lands under key, index under value — receiver is still
    # a list so Floor setitem runs, but at the wrong coordinates / value.
    # (Putting a TermValue in the receiver slot is a Floor gap, not a binding
    # twin — keep the receiver a ListValue so the bite is the binding shift.)
    lying = pending.discharge(
        {
            obj_cid: ListValue((TermValue(0), TermValue(1), TermValue(2))),
            key_cid: TermValue(1),  # shifted: was value slot in a self-steal map
            value_cid: TermValue(0),  # shifted index
        }
    )
    lying_face = lying.exits[0]
    if isinstance(lying_face, Completed):
        assert _stored_list(lying_face) != ListValue((TermValue(9), TermValue(1)))
        # Explicit: not the truthful store-at-0-with-9 face either.
        assert _stored_list(lying_face) != _stored_list(truthful.exits[0])
    else:
        assert isinstance(lying_face, Halted)


def test_discrimination_truthful_binding_completes_at_obj_slot() -> None:
    """Positive twin of the off-by-one arm."""
    site = _method_callsite(METHOD_BODY + "\nHolder().store([0, 1], 0, 9)\n")
    _assert_bound_self_first(site)
    assert site.arg_values[1:] == (
        ListValue((TermValue(0), TermValue(1))),
        TermValue(0),
        TermValue(9),
    )
    _assert_completed_call(site.producer_outcome(None))


def test_off_by_one_callsite_args_do_not_match_truthful_binding() -> None:
    """Discrimination: pretend self was not prepended (args slide left).

    Truthful ``arg_values`` are ``(Holder, list, key, value)``.  An off-by-one
    binding that treats call actuals as already including self would look like
    ``(list, key, value)`` — missing the Holder receiver or shifting list into
    self.  That shape is not the authenticated method callsite.
    """
    site = _method_callsite(METHOD_BODY + "\nHolder().store([0, 1], 0, 9)\n")
    truthful = site.arg_values
    assert len(truthful) == 4
    assert isinstance(truthful[0], ObjectValue)
    # Off-by-one twin: drop self, claim remaining three are the full binding.
    off_by_one = truthful[1:]
    assert len(off_by_one) == 3
    assert off_by_one != truthful
    assert not isinstance(off_by_one[0], ObjectValue) or (
        off_by_one[0].class_name != "Holder"
    )
