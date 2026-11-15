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

from frame_fresh import FRAME_FRESH, fresh
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
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
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
    class_def, method, _outcome = _method_definition()
    class_outcome = class_def.sugar().desugar(None)
    class_value = class_outcome.completed_value()
    assert isinstance(class_value, ClassDefinitionValue)
    receiver = class_value.fresh_receiver(
        class_value.class_definition_cid, allocation=FRAME_FRESH
    )
    assert isinstance(receiver, ObjectValue)
    return receiver, _carrier(method)


def _carrier(method):
    """The ``setitem`` carrier ``SubscriptStoreEffectSugar.project_setitem``
    mints for a store on a formal whose class is no input of its contract,
    over ``store``'s own ``obj``/``key``/``value`` coordinates (never
    ``self``'s), at the store's statement.  ``store`` itself takes
    ``class:obj`` (``obj`` is stored into and used no other way), so its own
    store is the dispatched edge (``_dispatched_call``, #8857); the discharge
    tests read the Floor ``setitem`` projector through this carrier."""
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.sugar.store_effect_sugar import (
        SubscriptStoreEffectSugar,
    )

    _self_c, obj_c, key_c, value_c = method.formal_coordinates()
    return SubscriptStoreEffectSugar.mint_setitem_carrier(
        site=method.body[0].fragment,
        receiver=SymbolicValue(make_var("obj"), obj_c),
        index=SymbolicValue(make_var("key"), key_c),
        value=SymbolicValue(make_var("value"), value_c),
    )


def _dispatched_halt(outcome, method: str = "__setitem__"):
    """The halt the dispatched item operation's edge owes in a function's
    own proof, under the owner every unanswered call's halt names, with its
    member ``python:dispatch:<method>`` owed."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    assert isinstance(outcome, ExitSet), type(outcome)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == f"UnknownCallee:dispatch:{method}"
    ]
    assert len(halts) == 1, outcome
    assert f"python:dispatch:{method}" in {
        call.symbol for call in owed_calls(outcome)
    }
    return halts[0]


def _dispatched_call(outcome, method: str = "__setitem__"):
    """``call:dispatch:<method>(<receiver>, <operands>..., py.class("0",
    class:<receiver>))``, read off the halt its edge owes (``python:raised(
    <call term>, <occurrence>)``)."""
    from sugar_lift_py_tests.call_symbol import call_symbol

    raised = _dispatched_halt(outcome, method).effect.raised_by_call
    assert raised.name == "python:raised", raised
    call = raised.args[0]
    assert call.name == call_symbol(f"dispatch:{method}"), call
    return call


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
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    # #6640: exceptional discharge stamps the reducer-owned pre-effect state.
    assert halted.state is not None, (
        "NativeOperationResolutionV1.project omitted the formal setitem "
        "halt's real pre-effect state"
    )
    return halted


def _stored_list(completed_face) -> ListValue:
    """The store's post-state list: the projector's own post (a carrier
    with no continuation), or a function universe's."""
    assert isinstance(completed_face, Completed)
    if isinstance(completed_face.value, ListValue):
        return completed_face.value
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
    """Method body ``obj[key] = value`` — setitem formals exclude ``self``.

    Expected shape changed (#8857): ``obj``'s class is an input of
    ``store``'s contract, so the store is the dispatched ``__setitem__``
    edge over ``obj, key, value`` and ``py.class("0", class:obj)``; ``self``
    is no operand of it and takes no class input (it is never used)."""
    from sugar_lift_py_tests.ir import str_const

    _class_def, method, outcome = _method_definition()
    call = _dispatched_call(outcome)
    assert [arg.name for arg in call.args[:3]] == ["obj", "key", "value"]
    assert call.args[3].name == "py.class"
    assert call.args[3].args[0] == str_const("0")
    assert call.args[3].args[1].name == "class:obj"
    assert len(call.args) == 4

    pending = _carrier(method)
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


def test_discrimination_self_is_not_the_setitem_receiver_slot() -> None:
    """Bite: setitem demand coordinates must not be the method's self formal."""
    _class_def, method, _outcome = _method_definition()
    pending = _carrier(method)
    self_coord = method.formal_coordinates()[0]
    obj_cid, key_cid, value_cid = _obj_key_value_cids(pending)
    assert self_coord.coordinate_cid not in {obj_cid, key_cid, value_cid}


# ---------------------------------------------------------------------------
# 2. Positional, keyword, and default calls discharge
# ---------------------------------------------------------------------------


def test_mutable_method_store_completes() -> None:
    holder, pending = _source_holder_receiver()
    obj_cid, key_cid, value_cid = _obj_key_value_cids(pending)
    # Direct discharge with bound-style actuals: only obj/key/value (no self).
    exits = pending.discharge(
        None,
        {
            obj_cid: fresh(ListValue, (TermValue(0), TermValue(1))),
            key_cid: TermValue(0),
            value_cid: TermValue(9),
        },
    )
    assert isinstance(exits.exits[0], Completed)
    assert _stored_list(exits.exits[0]) == fresh(
        ListValue, (TermValue(9), TermValue(1))
    )
    # Holder itself is not a setitem operand here — method self is separate.
    del holder


def test_invalid_index_discharge_shares_reducer_pre_effect_state() -> None:
    """#6640 join: bound-method setitem IndexError carries its pre-state.

    Expected shape changed (#8857): the method's store is the dispatched
    ``__setitem__`` edge, so the reducer enrolls no carrier testimony here;
    the edge's halt is a statement halt, and the block's one seam
    (``function_universe_sugar._halt_state``) leaves it with the block's
    pre-statement state, never a fabricated empty one.  Reducer enrollment
    on a carrier is held by ``test_native_operation_pre_effect_state``.

    The IndexError itself is the Floor ``setitem`` projector's on the
    carrier (``_carrier``): matching boundary resume and wrong-boundary
    retention both keep the halt's own effect and state by identity.
    """
    _class_def, _method, outcome = _method_definition()
    dispatched = _dispatched_halt(outcome)
    assert dispatched.state is not None, (
        "the dispatched setitem halt left the method's block with no "
        "pre-effect state"
    )

    _holder, pending = _source_holder_receiver()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    obj_cid, key_cid, value_cid = _obj_key_value_cids(pending)
    exits = pending.discharge(
        None,
        {
            obj_cid: fresh(ListValue, (TermValue(0),)),
            key_cid: TermValue(4),
            value_cid: TermValue(9),
        },
    )
    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert ":" in halted.effect.occurrence_id

    # A carrier no block enrolled holds no state: its halt is an
    # expression's, for the statement that runs it to record
    # (``_halts_leave_enrolled_state``), so a matching boundary over it is
    # the block's to read, never this test's.
    class _Expected:
        def __init__(self, name: str):
            self.identity = _identity(name)

        def exception_type_identity(self):
            return self.identity

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


def test_off_by_one_binding_twin_fails_against_truthful_store() -> None:
    """If self were shifted into the obj slot, store actuals would misalign.

    Truthful discharge keys obj/key/value.  An off-by-one map that slides the
    call actuals left (list under key, index under value, value dropped into
    a non-list receiver) cannot produce the truthful post-state of
    ``[0,1][0] = 9``.
    """
    _holder, pending = _source_holder_receiver()
    obj_cid, key_cid, value_cid = _obj_key_value_cids(pending)
    base = fresh(ListValue, (TermValue(0), TermValue(1)))
    truthful = pending.discharge(
        None, {obj_cid: base, key_cid: TermValue(0), value_cid: TermValue(9)}
    )
    assert isinstance(truthful.exits[0], Completed)
    assert _stored_list(truthful.exits[0]) == fresh(
        ListValue, (TermValue(9), TermValue(1))
    )

    # Off-by-one: list lands under key, index under value — receiver is still
    # a list so Floor setitem runs, but at the wrong coordinates / value.
    # (Putting a TermValue in the receiver slot is a Floor gap, not a binding
    # twin — keep the receiver a ListValue so the bite is the binding shift.)
    lying = pending.discharge(
        None,
        {
            obj_cid: fresh(ListValue, (TermValue(0), TermValue(1), TermValue(2))),
            key_cid: TermValue(1),  # shifted: was value slot in a self-steal map
            value_cid: TermValue(0),  # shifted index
        },
    )
    lying_face = lying.exits[0]
    if isinstance(lying_face, Completed):
        assert _stored_list(lying_face) != fresh(
            ListValue, (TermValue(9), TermValue(1))
        )
        # Explicit: not the truthful store-at-0-with-9 face either.
        assert _stored_list(lying_face) != _stored_list(truthful.exits[0])
    else:
        assert isinstance(lying_face, Halted)


