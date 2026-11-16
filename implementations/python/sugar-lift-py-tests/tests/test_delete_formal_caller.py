"""Formal ``del obj[key]`` through the one item mutation; ``del obj.field``
through the one attribute mutation.

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

An attribute delete mints no carrier either (#7757, audit 2 row NEW-1):
``helper2``'s ``del obj.field`` is the one attribute mutation,
``store_effect_sugar.attribute_mutation("__delattr__", r, "field", (),
...)``, ``type(r).__delattr__(r, "field")``:

  1. ``r`` a formal whose class is an input here (``helper3``'s ``obj``: a
     method of it is called) -> the dispatched edge
     ``call:dispatch:__delattr__(obj, "field", ..., py.class("0",
     class:obj))``, owed with its halt kept;
  2. ``r`` any other formal (``helper2``'s ``obj``: an attribute delete alone
     makes no class input) -> the undecided delete
     (``undecided_attribute_mutation_faces``): it completes only under
     ``python:delattr.completes(...)`` or raises something undetermined
     (owner ``UndecidedDelattr``), both faces owing the undecided member;
  3. ``r``'s type decided by the lift -> its floor's own ``delattr``: a
     present field completes gone, a getter-only property is the named
     ``AttributeError``; a name the fields do not hold is the dispatched
     ``__delattr__`` (the lift never decides a member's absence), with no
     class the instance names the undecided delete (owner
     ``ObjectValue.delattr``).

Equality tooth: production-minted operator set == projector-table keys, and
neither holds ``setitem``, ``delitem`` or ``delattr_named``.

Out of scope: Name deletion (``del name`` / DeleteNameSugar) -- neither the
item nor the attribute mutation.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

import pytest
from frame_fresh import FRAME_FRESH, fresh

from sugar_lift_py_tests import caller_parameter_contract
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
    attribute_mutation,
    item_mutation,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile

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


def _undecided_delete(
    outcome,
    *,
    stated: bool = True,
    owner: str = "UndecidedDelitem",
    noun: str = "delitem",
) -> Halted:
    """Arm 3 of the one item mutation: ``del r[k]`` where nothing here
    decides ``type(r)`` (``undecided_item_mutation_faces``).  The delete
    completes only under ``python:delitem.completes(...)`` or raises
    something undetermined (owner ``UndecidedDelitem``), and BOTH faces owe
    the undecided member (``unanswered_call(None, <site>)``).  It is no
    carrier and no completion decided here.  ``stated``: the halt is kept
    with the state the block reached before it (a function's reduction).

    ``owner="UndecidedDelattr", noun="delattr"``: the same law for ``del
    p.f`` on a formal whose class is no input
    (``undecided_attribute_mutation_faces``)."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.unanswered_calls import owed_calls, unanswered_call

    assert isinstance(outcome, ExitSet), type(outcome)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == owner
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
        assert f"python:{noun}.completes" in str(face.guard), face.guard
        assert owed in face.owed
    assert outcome.completed_value() is None
    return halt


def _delattr_helper():
    """``helper2`` alone and its own proof's reduction.  An attribute delete
    alone gives ``obj`` no class input (``nodes._receiver_uses``: it is an
    attribute receiver, neither received nor blocked), so nothing here
    decides ``type(obj).__delattr__``: the undecided delete."""
    source = "def helper2(obj):\n    del obj.field\n"
    tree = _tree(source, "delattr_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _delattr_dispatched_helper():
    """``helper3`` alone: a method of ``obj`` is called (after the delete,
    so the delete reads the formal itself), which makes ``obj``'s class an
    input of its contract (``nodes._receiver_class_parameters``), so ``del
    obj.field`` is ``type(obj).__delattr__(obj, "field")``: the dispatched
    edge, owed as it stands with its halt kept."""
    source = "def helper3(obj):\n    del obj.field\n    obj.close()\n"
    tree = _tree(source, "delattr_dispatched_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _undecided_attribute_delete(outcome, *, stated: bool = True) -> Halted:
    """``del p.f`` on a formal whose class is no input: the undecided
    attribute delete, never a carrier."""
    return _undecided_delete(
        outcome, stated=stated, owner="UndecidedDelattr", noun="delattr"
    )


def _receiver_class_rides(call, receiver: str) -> None:
    """``py.class("0", class:<receiver>)`` rides among the dispatched call's
    arguments (after the actuals; a decided name actual's own class may ride
    beside it)."""
    from sugar_lift_py_tests.ir import str_const

    rides = [
        arg
        for arg in call.args
        if getattr(arg, "name", None) == "py.class" and arg.args[0] == str_const("0")
    ]
    assert len(rides) == 1, call
    assert rides[0].args[1].name == f"class:{receiver}", rides[0]


def _attr_door(receiver) -> ExitSet:
    """``del receiver.field`` through the one attribute mutation at
    ``helper2``'s delete, the receiver the caller's decided actual: its
    floor's own ``delattr``, every face of it kept."""
    function, _ = _delattr_helper()
    return attribute_mutation(
        "__delattr__", receiver, "field", (), function.body[0].fragment, None, unit=None
    )


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


def test_attribute_mutation_mints_no_carrier_producer() -> None:
    """No attribute store or delete producer mints a carrier: the one
    attribute mutation is the door (``store_effect_sugar.
    attribute_mutation``, #7757 audit 2 row NEW-1)."""
    assert not hasattr(AttributeDeleteEffectSugar, "mint_delattr_named_carrier")
    assert not hasattr(store_effect_sugar, "mint_setattr_named_carrier")
    assert not hasattr(store_effect_sugar, "project_setattr")
    assert callable(attribute_mutation)


def test_item_mutation_has_no_projector() -> None:
    """``setitem`` / ``delitem`` left the projector table with their
    carrier: nothing discharges an item mutation on a caller's actuals."""
    assert not hasattr(caller_parameter_contract, "_project_delitem")


def test_attribute_mutation_has_no_projector() -> None:
    """``setattr_named`` / ``delattr_named`` left the projector table with
    their carrier: nothing discharges an attribute mutation on a caller's
    actuals."""
    assert not hasattr(caller_parameter_contract, "_project_delattr_named")


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

    # The dispatched attribute delete takes ``__delattr__(self, name)``'s
    # order: the receiver first, then the static name, then the receiver's
    # class input.
    _, dispatched_attr = _delattr_dispatched_helper()
    call = _dispatched_call(dispatched_attr, "__delattr__")
    assert call.args[0].name == "obj"
    assert "field" in str(call.args[1]), call.args[1]
    _receiver_class_rides(call, "obj")

    # The one attribute mutation takes the receiver, then the static name,
    # then its operands (none for a delete).
    assert list(inspect.signature(attribute_mutation).parameters) == [
        "method",
        "receiver",
        "attr",
        "operands",
        "site",
        "ctx",
        "unit",
    ]


def test_name_deletion_is_out_of_scope_for_delitem_and_delattr() -> None:
    """``del name`` is DeleteNameSugar territory — neither mutation."""
    source = "def helper(x):\n    del x\n"
    tree = _tree(source, "name_delete_out_of_scope.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    function.sugar().desugar(None)
    # Positive: a subscript delete is the one item mutation (the dispatched
    # ``__delitem__`` on a class-input formal, the undecided delete on a
    # formal whose class is no input), an attribute delete the one attribute
    # mutation (the same two arms).
    _, item = _delitem_undecided_helper()
    _undecided_delete(item)
    _, dispatched = _delitem_helper()
    _dispatched_call(dispatched)
    _, attr = _delattr_helper()
    _undecided_attribute_delete(attr)
    _, dispatched_attr = _delattr_dispatched_helper()
    _dispatched_call(dispatched_attr, "__delattr__")


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


def test_helper2_alone_is_the_undecided_attribute_delete() -> None:
    """``def helper2(obj): del obj.field`` → the undecided attribute delete
    (``obj``'s class is no input): no carrier and no dispatched edge, owed
    on both faces with its halt and state kept, never a completion."""
    _, outcome = _delattr_helper()
    _undecided_attribute_delete(outcome)
    assert not [
        face
        for face in outcome.halts()
        if str(face.effect.producer_node_owner).startswith("UnknownCallee:dispatch:")
    ]


def test_class_input_formal_attribute_delete_is_the_dispatched_delattr() -> None:
    """``obj``'s class an input (a method of it is called) → ``del
    obj.field`` is the dispatched ``__delattr__`` edge, owed with its halt
    kept; never the undecided delete beside it, never a carrier."""
    _, outcome = _delattr_dispatched_helper()
    call = _dispatched_call(outcome, "__delattr__")
    _receiver_class_rides(call, "obj")
    assert not [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UndecidedDelattr"
    ]
    assert outcome.halts()


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
    receiver = ObjectValue(
        class_name="Widget",
        fields=(ObjectField("field", TermValue(7)),),
        methods=(),
        allocation=FRAME_FRESH,
    )
    exits = _attr_door(receiver)
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


def _the_dispatched_attribute_delete(exits) -> None:
    """``del o.field`` on a source instance: ``type(o).__delattr__``, the one
    dispatched delete whose halts prove's walk decides (#7757 H1c), or, where
    no class is named, the one undecided attribute mutation.  Both faces are
    kept, and the lift names no ``AttributeError`` of its own."""
    assert isinstance(exits, ExitSet)
    assert exits.halts(), exits
    assert any(isinstance(face, Completed) for face in exits.exits), exits
    for halt in exits.halts():
        assert getattr(halt.effect, "exception_type_coordinate", None) != _identity(
            "AttributeError"
        ), halt.effect


def test_missing_attribute_is_the_undecided_delattr_and_keeps_pre_effect() -> None:
    # The floor's own face over the decided actual.  A name the recorded
    # fields do not hold is not decided absent here (#7757 L3, #9039/#9043/
    # #9049): ``del receiver.field`` is the dispatched ``__delattr__``; with
    # no class the instance names, nothing decides it, so it is the one
    # undecided attribute mutation (``ObjectValue._dispatched_delattr``),
    # both faces kept and owed, never an ``AttributeError`` named here.
    receiver = ObjectValue(
        class_name="Widget", fields=(), methods=(), allocation=FRAME_FRESH
    )
    _undecided_delete(
        _attr_door(receiver),
        stated=False,
        owner="ObjectValue.delattr",
        noun="delattr",
    )
    # In a function's reduction the attribute delete's halt leaves with the
    # block's record (``halts_at_statement_head``): the earlier store in it.
    # No carrier enrolls a pre-effect state to compare against any more.
    source = (
        "def helper2(obj):\n"
        "    a = [0]\n"
        "    a[0] = 9\n"
        "    del obj.field\n"
    )
    function = next(
        node
        for node in _tree(source, "delattr_after_store.py").nodes()
        if isinstance(node, FunctionDef)
    )
    _holds_earlier_store(_undecided_attribute_delete(function.sugar().desugar(None)))


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
    """Property is readable but the read never decides the delete (read ≠
    delete authority): the delete is the dispatched ``__delattr__``, whose
    halt face is kept, never a completion alone and never an
    ``AttributeError`` the lift decides (#7757 H1c)."""

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
    _the_dispatched_attribute_delete(_attr_door(receiver))


def test_discrimination_writable_field_is_not_attributeerror_delete() -> None:
    receiver = ObjectValue(
        class_name="Widget",
        fields=(ObjectField("field", TermValue(1)),),
        methods=(),
        allocation=FRAME_FRESH,
    )
    _the_dispatched_attribute_delete(_attr_door(receiver))


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
