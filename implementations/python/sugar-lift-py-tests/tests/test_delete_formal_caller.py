"""Formal ``del obj[key]`` through the one item mutation; ``delattr_named``
through the n-ary projector family.

Python semantic law made constructible:

  def helper(obj, key):
      del obj[key]

  def helper2(obj):
      del obj.field

An item delete mints no carrier (#7757 step 7): every ``del r[k]`` is the one
item mutation, ``store_effect_sugar.item_mutation("__delitem__", r, (k,),
...)``, whatever ``r`` is:

  1. ``r``'s type binds no ``__delitem__`` -> its ``TypeError``;
  2. ``r``'s class is an input here (``helper``'s ``obj``: deleted from and
     used no other way, ``nodes._receiver_class_parameters``, #8857) -> the
     dispatched edge ``call:dispatch:__delitem__(obj, key, py.class("0",
     class:obj))``, owed with its halt kept, answered at prove by the class
     each caller binds (``list``/``dict.__delitem__``'s law, #8864);
  3. ``r``'s type is not decided here (a formal whose class is no input:
     ``def helper(obj, key): del obj[key]; return obj`` reads ``obj`` bare)
     -> the undecided delete (``undecided_item_mutation_faces``): it
     completes only under ``python:delitem.completes(...)`` or raises
     something undetermined (owner ``UndecidedDelitem``), both faces owing
     the undecided member;
  4. ``r``'s type decided by the lift -> its floor's own ``delitem``: a
     mutable receiver completes with the element gone, a missing key is the
     named ``KeyError``, an index out of range the named ``IndexError``.

No delete waits on a caller's actual.  The floor faces (arm 4) are read off
the door over the decided actual, and the state a delete halt leaves with off
a function whose receiver its own frame built (the block's prefix,
``halts_at_statement_head``): earlier bindings survive a later delete halt.

``helper2``'s ``del obj.field`` keeps its ``delattr_named`` carrier:

  operator ``delattr_named``  (~ ``__delattr__(self, name)``)
  operands ``(receiver, StringValue(name))``
  coordinates ``(receiver.formal, None)``
  projector: ``_project_delattr_named(receiver, name, site)``
  producer: ``AttributeDeleteEffectSugar.mint_delattr_named_carrier``

Equality tooth: production-minted operator set == projector-table keys, and
neither holds ``setitem`` or ``delitem``.

Out of scope: Name deletion (``del name`` / DeleteNameSugar) -- not delitem,
not delattr_named.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

import pytest
from frame_fresh import FRAME_FRESH, fresh

from sugar_lift_py_tests import caller_parameter_contract
from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
    _project_delattr_named,
    production_native_operation_operators,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    BytesValue,
    DictValue,
    ListValue,
    ObjectField,
    ObjectMethodValue,
    ObjectValue,
    SliceValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.delete_effect_sugar import (
    AttributeDeleteEffectSugar,
    SubscriptDeleteEffectSugar,
)
from sugar_lift_py_tests.sugar import store_effect_sugar
from sugar_lift_py_tests.sugar.store_effect_sugar import (
    SubscriptStoreEffectSugar,
    item_mutation,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile

# ---------------------------------------------------------------------------
# Exact missing producer method names (valid deliverable when red)
# ---------------------------------------------------------------------------

MISSING_DELATTR_PRODUCER = (
    "AttributeDeleteEffectSugar.mint_delattr_named_carrier"
    " — formal delattr_named producer mirroring "
    "store_effect_sugar.mint_setattr_named_carrier; "
    "operator='delattr_named', operands=(receiver, StringValue(name)), "
    "projector receiver.delattr(name.value, site)"
)

MISSING_DELATTR_PROJECTOR = (
    "_NATIVE_OPERATION_PROJECTORS['delattr_named'] "
    "— lambda receiver, name, site: receiver.delattr(name.value, site)"
)

# A function whose own frame built the receiver (decided): its delete is the
# floor's own, and a halt leaves the block with the prefix it reached -- the
# list ``a[0] = 9`` stored before it included.
FRAME_MISSING_KEY = (
    "def frame():\n"
    "    a = [0]\n"
    "    a[0] = 9\n"
    "    obj = {'a': 1}\n"
    "    del obj['missing']\n"
)
FRAME_BAD_INDEX = (
    "def frame():\n"
    "    a = [0]\n"
    "    a[0] = 9\n"
    "    obj = [0]\n"
    "    del obj[4]\n"
)
_EARLIER_STORE = fresh(ListValue, (TermValue(9),))


def _tree(source: str, name: str = "delete_formal_caller.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def _delitem_helper():
    """``helper`` alone and its own proof's reduction.

    ``obj`` is deleted from and used no other way, so its class is an input
    of ``helper``'s contract (``nodes._receiver_class_parameters``) and
    ``del obj[key]`` is ``type(obj).__delitem__(obj, key)``: the dispatched
    edge (``receiver_dispatch.dispatch_edge_call``, #8857), owed as it
    stands with its halt kept, answered at prove by the class a caller binds
    (``list.__delitem__`` / ``dict.__delitem__``'s law, #8864)."""
    source = "def helper(obj, key):\n    del obj[key]\n"
    tree = _tree(source, "delitem_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _delitem_undecided_helper():
    """The same delete on a formal whose class is no input of its contract:
    ``return obj`` reads ``obj`` bare (``nodes._receiver_uses``: blocked), so
    nothing here decides ``type(obj)`` and the one item mutation is the
    undecided delete (arm 3), never a carrier waiting on the caller."""
    source = "def helper(obj, key):\n    del obj[key]\n    return obj\n"
    tree = _tree(source, "delitem_undecided_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _dispatched_call(outcome, method: str = "__delitem__"):
    """The dispatched item operation's coordinate in a helper's own proof:
    ``call:dispatch:<method>(<receiver>, <operands>..., py.class("0",
    class:<receiver>))``, read off the halt its edge owes (``python:raised(
    <call term>, <occurrence>)``), under the owner every unanswered call's
    halt names."""
    from sugar_lift_py_tests.call_symbol import call_symbol
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
    raised = halts[0].effect.raised_by_call
    assert raised.name == "python:raised", raised
    call = raised.args[0]
    assert call.name == call_symbol(f"dispatch:{method}"), call
    return call


def _class_input(call, receiver: str) -> None:
    """The dispatched call's receiver class rides last, as the class input
    of the receiver's parameter: ``py.class("0", class:<receiver>)``."""
    from sugar_lift_py_tests.ir import str_const

    rides = call.args[-1]
    assert rides.name == "py.class", rides
    assert rides.args[0] == str_const("0")
    assert rides.args[1].name == f"class:{receiver}", rides


def _undecided_delete(outcome, *, stated: bool = True) -> Halted:
    """Arm 3 of the one item mutation: ``del r[k]`` where nothing here
    decides ``type(r)`` (``undecided_item_mutation_faces``).  The delete
    completes only under ``python:delitem.completes(...)`` or raises
    something undetermined (owner ``UndecidedDelitem``), and BOTH faces owe
    the undecided member (``unanswered_call(None, <site>)``).  It is no
    carrier and no completion decided here.  ``stated``: the halt is kept
    with the state the block reached before it (a function's reduction)."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.unanswered_calls import owed_calls, unanswered_call

    assert isinstance(outcome, ExitSet), type(outcome)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UndecidedDelitem"
    ]
    assert len(halts) == 1, outcome
    (halt,) = halts
    assert isinstance(halt.effect, UndeterminedRaiseEffect), halt.effect
    if stated:
        assert halt.state is not None, "the undecided delete's halt dropped its state"
    owed = unanswered_call(None, halt.effect.site)
    assert owed in owed_calls(outcome)
    assert owed in halt.owed
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    for face in completed:
        assert "python:delitem.completes" in str(face.guard), face.guard
        assert owed in face.owed
    assert outcome.completed_value() is None
    return halt


def _delattr_helper():
    source = "def helper2(obj):\n    del obj.field\n"
    tree = _tree(source, "delattr_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _require_delattr_carrier(pending) -> NativeOperationExitCarrierV1:
    if not isinstance(pending, NativeOperationExitCarrierV1):
        raise AssertionError(
            f"missing producer {MISSING_DELATTR_PRODUCER}: "
            f"helper2 alone must mint undischarged delattr_named carrier, "
            f"got {type(pending).__name__} {pending!r:.200}"
        )
    if pending.demand.operator != "delattr_named":
        raise AssertionError(
            f"missing producer {MISSING_DELATTR_PRODUCER}: "
            f"expected operator delattr_named, got {pending.demand.operator!r}"
        )
    if "delattr_named" not in _NATIVE_OPERATION_PROJECTORS:
        raise AssertionError(f"missing projector {MISSING_DELATTR_PROJECTOR}")
    return pending


def _door(receiver, key) -> ExitSet:
    """``del receiver[key]`` through the one item mutation at ``helper``'s
    delete, the receiver the caller's decided actual: its floor's own
    ``delitem`` (arm 4), every face of it kept."""
    return item_mutation(
        "__delitem__", receiver, (key,), _floor_site(), None, unit=None
    )


def _frame_halt(source: str, expected: str) -> Halted:
    """``source``'s one function reduced: its delete, on a receiver its own
    frame built, halts with the named ``expected`` and the state the block
    reached before it."""
    tree = _tree(source, "delete_frame_halt.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    outcome = function.sugar().desugar(None)
    assert isinstance(outcome, ExitSet), type(outcome)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    return _assert_named_halt(outcome, expected)


def _assert_named_halt(outcome, expected: str, *, stated: bool = True) -> Halted:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity(expected)
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    if stated:
        assert halted.state is not None, (
            "delete halt omitted the real pre-effect state "
            "(the block's prefix, halts_at_statement_head)"
        )
    return halted


def _holds_earlier_store(halted: Halted) -> None:
    """The halt's state is the block before the delete: ``a[0] = 9`` in it,
    never an empty, rolled-back record."""
    assert halted.state is not None
    assert any(
        isinstance(entry, ListValue) and entry == _EARLIER_STORE
        for entry in halted.state.entries
    ), f"earlier store absent from entries={halted.state.entries!r}"


def _deleted_list(completed_face) -> ListValue:
    assert isinstance(completed_face, Completed)
    value = completed_face.value
    if isinstance(value, ListValue):
        return value
    record = getattr(value, "record", None)
    if record is not None:
        # The delete's post-state, and the same list where a helper's
        # ``return obj`` returns it.
        lists = [s for s in record.statements if isinstance(s, ListValue)] + [
            s.value
            for s in record.statements
            if isinstance(s, ReturnValue) and isinstance(s.value, ListValue)
        ]
        assert lists, record.statements
        assert all(item == lists[0] for item in lists), lists
        return lists[0]
    raise AssertionError(f"no ListValue post-state: {type(value).__name__}")


# ===========================================================================
# The carrier machinery is deleted (#7757 step 7)
# ===========================================================================


def test_item_mutation_mints_no_carrier_producer() -> None:
    """No item store or delete producer mints a carrier: the one item
    mutation is the door (``store_effect_sugar.item_mutation``)."""
    for owner, deleted in (
        (SubscriptStoreEffectSugar, "mint_setitem_carrier"),
        (SubscriptStoreEffectSugar, "project_setitem"),
        (SubscriptDeleteEffectSugar, "mint_delitem_carrier"),
        (SubscriptDeleteEffectSugar, "project_delitem"),
    ):
        assert not hasattr(owner, deleted), f"{owner.__name__}.{deleted}"
    assert not hasattr(store_effect_sugar, "_undecided_setitem_faces")
    assert callable(item_mutation)


def test_delattr_producer_method_is_enrolled_or_named_missing() -> None:
    assert hasattr(store_effect_sugar, "mint_setattr_named_carrier")
    if not hasattr(AttributeDeleteEffectSugar, "mint_delattr_named_carrier"):
        raise AssertionError(f"missing producer method {MISSING_DELATTR_PRODUCER}")


def test_item_mutation_has_no_projector() -> None:
    """``setitem`` / ``delitem`` left the projector table with their
    carrier: nothing discharges an item mutation on a caller's actuals."""
    assert "setitem" not in _NATIVE_OPERATION_PROJECTORS
    assert "delitem" not in _NATIVE_OPERATION_PROJECTORS
    assert not hasattr(caller_parameter_contract, "_project_delitem")


def test_delattr_projector_is_enrolled_or_named_missing() -> None:
    """Explicit ``delattr_named(receiver, name, site)`` projector enrolled."""
    assert "setattr_named" in _NATIVE_OPERATION_PROJECTORS
    if "delattr_named" not in _NATIVE_OPERATION_PROJECTORS:
        raise AssertionError(f"missing projector {MISSING_DELATTR_PROJECTOR}")
    projector = _NATIVE_OPERATION_PROJECTORS["delattr_named"]
    assert projector is _project_delattr_named
    parameters = tuple(inspect.signature(projector).parameters)
    assert parameters == ("receiver", "name", "site", "ctx")


def test_production_minted_operators_equal_projector_keys_including_delete() -> None:
    """Equality tooth: production set == projector keys; ``delattr_named``
    in both, the item mutation in neither."""
    production = production_native_operation_operators()
    projectors = frozenset(_NATIVE_OPERATION_PROJECTORS)
    assert production == projectors, (
        f"missing_projectors={sorted(production - projectors)} "
        f"orphan_projectors={sorted(projectors - production)}"
    )
    assert "delattr_named" in production
    assert "delattr_named" in projectors
    assert {"setitem", "delitem"}.isdisjoint(production | projectors)


def test_ordered_operands_and_formals_match_protocol_signatures() -> None:
    """Operand order is protocol order, not source-eval order."""
    # The dispatched edge takes ``__delitem__(self, key)``'s order: the
    # receiver first, then the key, then the receiver's class input (#8857).
    _, dispatched = _delitem_helper()
    call = _dispatched_call(dispatched)
    assert [arg.name for arg in call.args[:2]] == ["obj", "key"]
    _class_input(call, "obj")
    assert len(call.args) == 3

    # The one item mutation takes the receiver, then the key (its operands).
    assert list(inspect.signature(item_mutation).parameters) == [
        "method",
        "receiver",
        "operands",
        "site",
        "ctx",
        "unit",
        "label",
    ]
    exits = _door(fresh(ListValue, (TermValue(0), TermValue(1))), TermValue(0))
    assert exits.completed_value() == fresh(ListValue, (TermValue(1),))

    _, delattr_c = _delattr_helper()
    delattr_c = _require_delattr_carrier(delattr_c)
    assert delattr_c.demand.operator == "delattr_named"
    assert delattr_c.demand.operand_coordinate_cids == (
        delattr_c.demand.operand_coordinate_cids[0],
        None,
    )
    assert isinstance(delattr_c.operands[1], StringValue)
    assert list(inspect.signature(_project_delattr_named).parameters) == [
        "receiver",
        "name",
        "site",
        "ctx",
    ]


def test_name_deletion_is_out_of_scope_for_delitem_and_delattr_named() -> None:
    """``del name`` is DeleteNameSugar territory — not delitem/delattr_named."""
    source = "def helper(x):\n    del x\n"
    tree = _tree(source, "name_delete_out_of_scope.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    pending = function.sugar().desugar(None)
    if isinstance(pending, NativeOperationExitCarrierV1):
        assert pending.demand.operator not in {
            "delitem",
            "delattr_named",
        }, "Name deletion must not mint delitem/delattr_named"
    # Positive: a subscript delete is the one item mutation (the dispatched
    # ``__delitem__`` on a class-input formal, the undecided delete on a
    # formal whose class is no input), an attribute delete its carrier.
    _, item = _delitem_undecided_helper()
    _undecided_delete(item)
    _, dispatched = _delitem_helper()
    _dispatched_call(dispatched)
    _, attr = _delattr_helper()
    assert _require_delattr_carrier(attr).demand.operator == "delattr_named"


# ===========================================================================
# Helper alone owes its delete
# ===========================================================================


def test_helper_alone_retains_undischarged_delitem_demand() -> None:
    """``def helper(obj, key): del obj[key]`` → the dispatched ``__delitem__``
    edge, owed with its halt (#8857); with ``obj`` blocked, the undecided
    delete, owed on both faces with its halt and state kept."""
    _, dispatched = _delitem_helper()
    call = _dispatched_call(dispatched)
    assert [arg.name for arg in call.args[:2]] == ["obj", "key"]
    _class_input(call, "obj")
    assert [face for face in dispatched.exits if isinstance(face, Completed)]

    _, undecided = _delitem_undecided_helper()
    _undecided_delete(undecided)


def test_helper2_alone_retains_undischarged_delattr_named_demand() -> None:
    """``def helper2(obj): del obj.field`` → undischarged delattr_named carrier."""
    _, pending = _delattr_helper()
    pending = _require_delattr_carrier(pending)
    assert len(pending.operands) == 2
    assert pending.demand.operand_coordinate_cids[0] is not None
    # Static attribute name slot is null — not a formal (mirrors setattr_named).
    assert pending.demand.operand_coordinate_cids[1] is None
    assert isinstance(pending.operands[1], StringValue)
    assert pending.operands[1].value == "field"


def test_discrimination_helper_alone_is_not_completed_delete() -> None:
    """An owed delete is not a completed empty body."""
    # The dispatched edge (#8857): its halt stands, and the delete is owed,
    # never a completion decided here.
    _, dispatched = _delitem_helper()
    _dispatched_call(dispatched)
    assert dispatched.halts()
    # The undecided delete, where ``obj``'s class is no input: a guarded
    # completion beside its kept halt, never a sole completion.
    _, undecided = _delitem_undecided_helper()
    _undecided_delete(undecided)
    assert undecided.halts()
    assert undecided.completed_value() is None


# ===========================================================================
# No caller actual: the delete is owed, never completed
# ===========================================================================


def test_missing_caller_actual_is_undischarged_not_completed() -> None:
    """No caller actual is waited on: the undecided delete is the cited
    unanswered face on both arms (#7825), never a fabricated completion."""
    _, undecided = _delitem_undecided_helper()
    _undecided_delete(undecided)


def test_partial_caller_actual_is_undischarged_discrimination() -> None:
    """A decided receiver completes the delete; an undecided one (the key
    decided, the receiver not) is the undecided delete, owed, not a
    completion."""
    completed = _door(fresh(ListValue, (TermValue(0),)), TermValue(0))
    assert isinstance(completed.exits[0], Completed)
    undecided = _door(SymbolicValue(make_var("obj")), TermValue(0))
    _undecided_delete(undecided, stated=False)


# ===========================================================================
# A decided receiver: the floor's own delete; mutable receiver completes gone
# ===========================================================================


def test_mutable_list_receiver_completes_delete_with_element_gone() -> None:
    """``del obj[0]`` on ``[0, 1]`` → ListValue([1])."""
    exits = _door(fresh(ListValue, (TermValue(0), TermValue(1))), TermValue(0))
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    assert _deleted_list(exits.exits[0]) == fresh(ListValue, (TermValue(1),))


def test_mutable_dict_receiver_completes_delete_with_key_gone() -> None:
    """``del obj[key]`` on dict with present key → empty entries."""
    exits = _door(
        fresh(DictValue, ((StringValue("a"), TermValue(1)),)), StringValue("a")
    )
    assert isinstance(exits.exits[0], Completed)
    value = exits.exits[0].value
    assert isinstance(value, DictValue), value
    assert value.entries == ()


def test_writable_field_delete_completes_with_attribute_gone() -> None:
    """``del obj.field`` on writable instance field → field absent."""
    _, pending = _delattr_helper()
    pending = _require_delattr_carrier(pending)
    obj_cid, _name_cid = pending.demand.operand_coordinate_cids
    receiver = ObjectValue(
        class_name="Widget",
        fields=(ObjectField("field", TermValue(7)),),
        methods=(),
        allocation=FRAME_FRESH,
    )
    exits = pending.discharge(None, {obj_cid: receiver})
    assert isinstance(exits.exits[0], Completed)
    stored = exits.exits[0].value
    record = getattr(stored, "record", None)
    objs = []
    if isinstance(stored, ObjectValue):
        objs = [stored]
    elif record is not None:
        objs = [s for s in record.statements if isinstance(s, ObjectValue)]
    assert objs, f"no ObjectValue post-state: {type(stored).__name__}"
    assert not any(f.name == "field" for f in objs[-1].fields), objs[-1].fields


def test_discrimination_completed_delete_is_not_halted() -> None:
    exits = _door(fresh(ListValue, (TermValue(0),)), TermValue(0))
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Halted)


# ===========================================================================
# Missing key / missing attribute → named exceptional faces + pre-effect
# ===========================================================================


def test_missing_dict_key_halts_with_named_keyerror_and_pre_effect_state() -> None:
    # The floor's own face over the decided actual.
    _assert_named_halt(
        _door(
            fresh(DictValue, ((StringValue("a"), TermValue(1)),)),
            StringValue("missing"),
        ),
        "KeyError",
        stated=False,
    )
    # In a function's reduction the halt leaves with the block's prefix.
    _holds_earlier_store(_frame_halt(FRAME_MISSING_KEY, "KeyError"))


def test_missing_list_index_halts_with_named_indexerror_and_pre_effect_state() -> None:
    _assert_named_halt(
        _door(fresh(ListValue, (TermValue(0),)), TermValue(4)),
        "IndexError",
        stated=False,
    )
    _holds_earlier_store(_frame_halt(FRAME_BAD_INDEX, "IndexError"))


def test_missing_attribute_halts_with_named_attributeerror_and_pre_effect() -> None:
    _, pending = _delattr_helper()
    pending = _require_delattr_carrier(pending)
    testimony = pending.pre_effect_state
    assert (
        testimony is not None
    ), "reducer did not enroll ReducerPreEffectStateV1 on formal delattr_named"
    obj_cid, _ = pending.demand.operand_coordinate_cids
    receiver = ObjectValue(
        class_name="Widget", fields=(), methods=(), allocation=FRAME_FRESH
    )
    exits = pending.discharge(None, {obj_cid: receiver})
    halted = _assert_named_halt(exits, "AttributeError")
    assert halted.state is testimony.state


def test_discrimination_present_key_is_not_keyerror() -> None:
    exits = _door(
        fresh(DictValue, ((StringValue("a"), TermValue(1)),)), StringValue("a")
    )
    assert isinstance(exits.exits[0], Completed)
    assert not isinstance(exits.exits[0], Halted)


# ===========================================================================
# Deletion does not roll back earlier bindings
# ===========================================================================


def test_deletion_does_not_roll_back_earlier_bindings_on_keyerror() -> None:
    """Prior store/bindings survive a KeyError delete halt.

    The halt's state is the block the reducer reached before the delete
    (``halts_at_statement_head``): ``a[0] = 9`` in it, never a fabricated
    empty block.  An undecided delete's halt keeps it the same way.
    """
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    halted = _frame_halt(FRAME_MISSING_KEY, "KeyError")
    _holds_earlier_store(halted)
    assert halted.state != _ReducedBlock((), True, ())

    source = (
        "def helper(obj, key):\n"
        "    a = [0]\n"
        "    a[0] = 9\n"
        "    del obj[key]\n"
        "    return obj\n"
    )
    function = next(
        node
        for node in _tree(source, "undecided_after_store.py").nodes()
        if isinstance(node, FunctionDef)
    )
    _holds_earlier_store(_undecided_delete(function.sugar().desugar(None)))


# ===========================================================================
# Swapped-operand and read-authorizes-delete twins
# ===========================================================================


def test_swapped_receiver_index_coordinates_rejected_against_truthful_delete() -> None:
    """A lying delete (receiver/index swapped) must not equal the truthful
    post-state.

    Swapped, the index sits in the receiver slot; Floor ``TermValue.delitem``
    refuses loudly (ConstructionPanic) or halts.  Either is a valid
    discrimination face — the lie must not complete the truthful list.
    """
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    original = fresh(ListValue, (TermValue(0), TermValue(1)))
    truthful_exits = _door(original, TermValue(0))
    assert isinstance(truthful_exits.exits[0], Completed)
    truthful_list = _deleted_list(truthful_exits.exits[0])
    assert truthful_list == fresh(ListValue, (TermValue(1),))
    try:
        lying_exits = _door(TermValue(0), original)
    except ConstructionPanic:
        # Receiver slot received TermValue — Floor refuses delitem. Discrimination holds.
        return
    lying_face = lying_exits.exits[0]
    if isinstance(lying_face, Completed):
        assert lying_face.value != truthful_list
    else:
        assert isinstance(lying_face, Halted)


def test_read_does_not_authorize_delete_on_getter_only_property() -> None:
    """Property is readable but delete must not complete (read ≠ delete authority)."""
    _, pending = _delattr_helper()
    pending = _require_delattr_carrier(pending)
    obj_cid, _ = pending.demand.operand_coordinate_cids

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

    # Getter-only property enrolled; no deleter.
    receiver = ObjectValue(
        class_name="Widget",
        fields=(),
        methods=(
            ObjectMethodValue(
                name="field",
                parameters=("self",),
                descriptor_kind="property",
            ),
        ),
        allocation=FRAME_FRESH,
    )
    assert any(
        m.name == "field" and m.descriptor_kind == "property" for m in receiver.methods
    )
    exits = pending.discharge(None, {obj_cid: receiver})
    halted = exits.exits[0]
    assert isinstance(
        halted, Halted
    ), "read-authorizes-delete twin: getter-only property must not complete delete"
    assert halted.effect.exception_type_coordinate == _identity("AttributeError")


def test_discrimination_writable_field_is_not_attributeerror_delete() -> None:
    _, pending = _delattr_helper()
    pending = _require_delattr_carrier(pending)
    obj_cid, _ = pending.demand.operand_coordinate_cids
    receiver = ObjectValue(
        class_name="Widget",
        fields=(ObjectField("field", TermValue(1)),),
        methods=(),
        allocation=FRAME_FRESH,
    )
    exits = pending.discharge(None, {obj_cid: receiver})
    assert isinstance(exits.exits[0], Completed)
    assert not isinstance(exits.exits[0], Halted)


# ===========================================================================
# Floor-level delete twins
# ===========================================================================


def _floor_site():
    """Genuine fragment locus for Floor delitem (not a string blame)."""
    function, _ = _delitem_helper()
    return function.body[0].fragment


@dataclass(frozen=True)
class _FloorSugar(Sugar):
    value: object

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)

    @classmethod
    def witnesses(cls):
        return ()


@pytest.mark.parametrize(
    ("receiver", "owner"),
    (
        (StringValue("abc"), "StringValue.delitem"),
        (BytesValue(b"abc"), "BytesValue.delitem"),
        (TupleValue((TermValue(1),)), "TupleValue.delitem"),
    ),
)
def test_immutable_slice_delete_has_exact_typeerror_occurrence(receiver, owner):
    site = _floor_site()
    outcome = SubscriptDeleteEffectSugar(
        _FloorSugar(receiver),
        _FloorSugar(SliceValue(TermValue(0), TermValue(1), None)),
        site,
    ).desugar(None)
    assert len(outcome.exits) == 1 and outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert halt.effect.exception_name == "TypeError"
    assert halt.effect.producer_node_owner == owner
    assert halt.effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


@pytest.mark.parametrize(
    "receiver",
    (
        StringValue("abc"),
        BytesValue(b"abc"),
        TupleValue((TermValue(1),)),
    ),
)
def test_immutable_slice_delete_cannot_fabricate_mutated_receiver(receiver):
    site = _floor_site()
    outcome = SubscriptDeleteEffectSugar(
        _FloorSugar(receiver),
        _FloorSugar(SliceValue(TermValue(0), TermValue(1), None)),
        site,
    ).desugar(None)
    assert outcome.completed_value() is None


def test_floor_list_delitem_completes_with_element_gone() -> None:
    """Floor ``ListValue.delitem`` already implements the delete post-state law."""
    result = fresh(ListValue, (TermValue(0), TermValue(1))).delitem(
        TermValue(0), _floor_site(), None
    )
    assert result.completed_value() is not None
    assert result.completed_value() == fresh(ListValue, (TermValue(1),))


def test_floor_list_delitem_out_of_range_is_named_indexerror() -> None:
    """Floor list delete IndexError (ground_index_error) — named exceptional face."""
    from sugar_lift_py_tests.effect import RaiseEffect

    result = fresh(ListValue, (TermValue(0),)).delitem(
        TermValue(5), _floor_site(), None
    )
    assert len(result.exits) == 1 and result.halts() == result.exits
    (halt,) = result.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "IndexError"


def test_floor_delete_is_not_the_formal_helper_twin() -> None:
    """Discrimination: a floor completion is not a helper's owed delete."""
    floor = fresh(ListValue, (TermValue(0),)).delitem(TermValue(0), _floor_site(), None)
    assert floor.completed_value() is not None
    _, dispatched = _delitem_helper()
    _dispatched_call(dispatched)
    assert not isinstance(dispatched.completed_value(), ListValue)
    _, undecided = _delitem_undecided_helper()
    _undecided_delete(undecided)
    assert not isinstance(undecided.completed_value(), ListValue)
