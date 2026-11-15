"""Positional-only and keyword-only binding through formal setitem.

Concrete signature:

    def helper(obj, /, key=0, *, value):
        obj[key] = value

Binding kinds (SourceCallFrame.bind_actuals):

  - ``obj``  positional-only  — must be positional; keyword is refused
  - ``key``  positional-or-keyword with default 0 — default, pos, or kw
  - ``value`` keyword-only required — must be keyword; missing is honest gap

Helper alone is the dispatched ``__setitem__`` edge since #8857: ``obj``'s
class is an input of its contract (a positional-only parameter's as any
other's), the edge owed, its halt kept with the state the store began from.
Callers carry their actuals by kind and the class of each decided actual
(``py.class``).  The ``setitem`` carrier (a store on a formal whose class is
no input) maps actuals onto the exact native-operation formal coordinates
(obj, key, value) in discharge order: mutable store completes; invalid
index yields named IndexError.

Does not touch carrier/ExitSet, setitem producer/projector/Floor, or
parameter-name side maps. No binder logic outside SourceCallFrame.bind_actuals.
"""

from __future__ import annotations

import inspect

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ListValue, TermValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

HELPER = "def helper(obj, /, key=0, *, value):\n    obj[key] = value\n"


def _tree(source: str, name: str = "setitem_param_kinds.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper():
    """``helper`` alone and its own proof's reduction.

    ``obj`` (positional-only) is stored into and used no other way, so its
    class is an input of ``helper``'s contract
    (``nodes._receiver_class_parameters``: positional-only, positional-or-
    keyword and keyword-only parameters alike) and ``obj[key] = value`` is
    ``type(obj).__setitem__(obj, key, value)``: the dispatched edge
    (``receiver_dispatch.dispatch_edge_call``, #8857), owed as it stands,
    resolved at prove at the class each caller binds (``list.__setitem__``'s
    law, #8864).  It is no ``setitem`` carrier."""
    tree = _tree(HELPER, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _dispatched_halt(outcome, method: str = "__setitem__"):
    """The one halt the dispatched item operation's edge owes in a helper's
    own proof, under the owner every unanswered call's halt names, its
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
    """The dispatched item operation's coordinate ``call:dispatch:<method>(
    <receiver>, <operands>..., py.class("0", class:<receiver>))``, read off
    the halt its edge owes (``python:raised(<call term>, <occurrence>)``)."""
    from sugar_lift_py_tests.call_symbol import call_symbol

    raised = _dispatched_halt(outcome, method).effect.raised_by_call
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


def _carrier():
    """The ``setitem`` carrier ``SubscriptStoreEffectSugar.project_setitem``
    mints for a store on a formal whose class is no input of its contract
    (an ``obj`` its body also reads bare, hands to code, or a nested
    function reads): one operation waiting for the caller's actuals, over
    ``helper``'s own formal coordinates (positional-only, positional-or-
    keyword, keyword-only), in discharge order.  Its discharge is the Floor
    ``setitem`` projector; the dispatched helper above never takes it."""
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.sugar.store_effect_sugar import (
        SubscriptStoreEffectSugar,
    )

    function, _outcome = _helper()
    obj_c, key_c, value_c = function.formal_coordinates()
    carrier = SubscriptStoreEffectSugar.mint_setitem_carrier(
        site=function.body[0].fragment,
        receiver=SymbolicValue(make_var("obj"), obj_c),
        index=SymbolicValue(make_var("key"), key_c),
        value=SymbolicValue(make_var("value"), value_c),
    )
    return function, carrier


def _class(key: str, name: str):
    """``py.class(<key>, python:builtin("<name>"))``: the class of an actual
    the caller decides, after the actuals (#8857)."""
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.receiver_dispatch import (
        CLASS_ARGUMENT,
        builtin_class_term,
    )

    return ctor(CLASS_ARGUMENT, [str_const(key), builtin_class_term(name)])


def _call(actuals: str):
    """A module-body call reduced alone: where the binder refuses the call
    (a missing or ill-kinded actual) it refuses here, by name."""
    tree = _tree(HELPER + f"\nhelper({actuals})\n")
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _edge(actuals: str):
    """``helper({actuals})`` in a caller's body, read off the caller's
    contract row (``function_universe_outcome``): a function called after
    import, so an omitted ``key`` binds what the ``def`` statement's module
    run evaluated.

    A same-file call is its coordinate and edge, joined at prove (#7757
    steps 5 and 6, #8705): the one binder binds the actuals by kind only to
    read what the call supplies, and the helper's ``setitem`` carrier is
    never discharged at the call.  The call completes under its
    ``completes`` atom and halts under the complement; returns the call
    value the row's one completed face returns."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    tree = _tree(HELPER + f"\n\ndef caller():\n    return helper({actuals})\n")
    caller = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "caller"
    )
    outcome = function_universe_outcome(caller)
    assert [face for face in outcome.exits if isinstance(face, Halted)], outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    returns = [
        s for s in completed[0].value.record.statements if isinstance(s, ReturnValue)
    ]
    assert returns, completed[0].value
    edge = returns[-1].value
    assert isinstance(edge, CallSiteValue), type(edge)
    return edge


def _coordinate(edge):
    """The call's coordinate ``call:<target>(<arguments>)`` the edge's value
    names: the completed face of the one unanswered call returns
    ``python:call_result(<call term>, <occurrence>)`` (#7757 steps 5 and 6,
    #8705), so the arguments prove's binder binds are the call term's,
    never the result's."""
    result = edge.term
    assert result.name == "python:call_result", result
    call = result.args[0]
    assert call.name.startswith("call:"), call
    return call


def _named(edge, kind: str, name: str, value: int):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        kind, [str_const(name), TermValue(value).to_term(owner=str(edge.site))]
    )


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def _stored_list(completed_face) -> ListValue:
    """The store's post-state list: the projector's own post (a carrier with
    no continuation), or a function universe's."""
    assert isinstance(completed_face, Completed)
    if isinstance(completed_face.value, ListValue):
        return completed_face.value
    record = getattr(completed_face.value, "record", None)
    assert record is not None
    lists = [s for s in record.statements if isinstance(s, ListValue)]
    assert len(lists) == 1, lists
    return lists[0]


# ---------------------------------------------------------------------------
# Helper alone → Undischarged setitem on exact formals
# ---------------------------------------------------------------------------


def test_helper_alone_is_undischarged_setitem_with_parameter_kinds() -> None:
    # Expected shape changed (#8857): the positional-only ``obj``'s class is
    # an input, so the store is the dispatched ``__setitem__`` edge over the
    # three formals in Python's order, owed, its halt kept with the state
    # the store began from; the carrier stands only where the class is no
    # input (``_carrier``).
    function, outcome = _helper()
    call = _dispatched_call(outcome)
    assert [arg.name for arg in call.args[:3]] == ["obj", "key", "value"]
    _class_input(call, "obj")
    assert len(call.args) == 4
    assert _dispatched_halt(outcome).state is not None
    assert [face for face in outcome.exits if isinstance(face, Completed)]
    kinds = tuple(c.parameter_kind for c in function.sugar().formal_coordinates)
    assert kinds == ("positional-only", "positional-or-keyword", "keyword-only")

    _, pending = _carrier()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"
    assert tuple(value.term.name for value in pending.operands) == (
        "obj",
        "key",
        "value",
    )
    # All three formals authenticate the setitem demand coordinates.
    assert pending.demand.operand_coordinate_cids == tuple(
        c.coordinate_cid for c in function.sugar().formal_coordinates
    )
    parameters = tuple(
        inspect.signature(_NATIVE_OPERATION_PROJECTORS["setitem"]).parameters
    )
    assert parameters == ("receiver", "index", "value", "site", "ctx")


def test_helper_alone_is_not_completed_discrimination() -> None:
    _, pending = _helper()
    with pytest.raises(AssertionError):
        assert isinstance(pending, Completed)


# ---------------------------------------------------------------------------
# Authenticated callers bind by kind to exact coordinates
# ---------------------------------------------------------------------------


def test_positional_only_receiver_and_keyword_only_value_complete() -> None:
    """``helper([0], 0, value=9)`` — pos-only obj, pos key, kw-only value.
    The edge carries the actuals as written; prove's one binder binds them
    to the helper's formals by kind (the call value no longer names the
    frame's parameters, #8705)."""
    edge = _edge("[0], 0, value=9")
    assert edge.arg_values == (
        fresh(ListValue, (TermValue(0),)),
        TermValue(0),
        TermValue(9),
    )
    # After the actuals ride the classes the caller decides (#8857): the
    # ``[0]`` it built is a ``list`` at ``"0"`` (what ``class:obj`` binds at
    # prove), the ``int`` key at ``"1"``, the keyword ``value`` by name.
    assert list(_coordinate(edge).args[1:]) == [
        TermValue(0).to_term(owner=str(edge.site)),
        _named(edge, "py.kwarg", "value", 9),
        _class("0", "list"),
        _class("1", "int"),
        _class("value", "int"),
    ]


def test_default_key_and_keyword_only_value_complete() -> None:
    """``helper([0], value=9)`` — key default 0 supplies the index formal,
    carried on the edge as ``py.default``; a default supplies no class."""
    edge = _edge("[0], value=9")
    assert edge.arg_values == (fresh(ListValue, (TermValue(0),)), TermValue(9))
    assert list(_coordinate(edge).args[1:]) == [
        _named(edge, "py.kwarg", "value", 9),
        _named(edge, "py.default", "key", 0),
        _class("0", "list"),
        _class("value", "int"),
    ]


def test_explicit_keyword_key_binds_same_key_formal() -> None:
    """``helper([0, 0], key=1, value=9)`` — key formal receives 1, store at 1.
    The edge names the formal ``key`` (``py.kwarg``); the frame's formal
    coordinate cids the followed call carried are gone with the follow
    (#8705, #8751): prove binds by name."""
    edge = _edge("[0, 0], key=1, value=9")
    assert edge.arg_values[1] == TermValue(1)
    assert edge.arg_values[2] == TermValue(9)
    assert list(_coordinate(edge).args[1:]) == [
        _named(edge, "py.kwarg", "key", 1),
        _named(edge, "py.kwarg", "value", 9),
        _class("0", "list"),
        _class("key", "int"),
        _class("value", "int"),
    ]


def test_callers_bind_to_exact_native_operation_coordinates() -> None:
    """Direct discharge uses the same formal cids as the setitem demand."""
    function, pending = _carrier()
    obj_cid, key_cid, value_cid = pending.demand.operand_coordinate_cids
    formals = function.sugar().formal_coordinates
    assert (obj_cid, key_cid, value_cid) == tuple(c.coordinate_cid for c in formals)
    assert formals[0].parameter_kind == "positional-only"
    assert formals[1].parameter_kind == "positional-or-keyword"
    assert formals[2].parameter_kind == "keyword-only"
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


# ---------------------------------------------------------------------------
# Mutable complete / invalid index with exact pre-effect state
# ---------------------------------------------------------------------------


def test_mutable_store_completes_via_kinds() -> None:
    _, pending = _carrier()
    obj_cid, key_cid, value_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        None,
        {
            obj_cid: fresh(ListValue, (TermValue(0),)),
            key_cid: TermValue(0),
            value_cid: TermValue(9),
        },
    )
    assert isinstance(exits, ExitSet)
    assert isinstance(exits.exits[0], Completed)
    assert _stored_list(exits.exits[0]) == fresh(ListValue, (TermValue(9),))


def test_invalid_index_named_indexerror_with_exact_pre_effect_state() -> None:
    # Expected shape changed (#8857): the helper's own store is the
    # dispatched edge, whose halt leaves with the state the store began
    # from (the block reducer's one record, ``_halt_state``); the named
    # IndexError is the carrier's projector, discharged below, and with the
    # dispatched edge it is ``list.__setitem__``'s law at prove (#8864).
    _, outcome = _helper()
    assert _dispatched_halt(outcome).state is not None
    _, pending = _carrier()
    obj_cid, key_cid, value_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        None,
        {
            obj_cid: fresh(ListValue, (TermValue(0),)),
            key_cid: TermValue(1),
            value_cid: TermValue(9),
        },
    )
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert not isinstance(halted, Completed)
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    assert not isinstance(getattr(halted, "value", None), UniverseValue)


def test_source_caller_invalid_index_preserves_state() -> None:
    # Expected verdict changed (#7757 steps 5 and 6, #8705): the source call
    # is its edge and owes its halt; the named IndexError with its state is
    # the helper's contract row discharged with these actuals
    # (``test_invalid_index_named_indexerror_with_exact_pre_effect_state``),
    # joined at the call by prove (#8690, #8749).
    edge = _edge("[0], key=1, value=9")
    assert edge.arg_values == (
        fresh(ListValue, (TermValue(0),)),
        TermValue(1),
        TermValue(9),
    )


def test_invalid_index_discrimination_not_completed() -> None:
    _, pending = _carrier()
    obj_cid, key_cid, value_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        None,
        {
            obj_cid: fresh(ListValue, (TermValue(0),)),
            key_cid: TermValue(1),
            value_cid: TermValue(9),
        },
    )
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Completed)
    # The helper's own halt is never stateless: it leaves with the state the
    # store began from.
    _, outcome = _helper()
    with pytest.raises(AssertionError):
        assert _dispatched_halt(outcome).state is None


# ---------------------------------------------------------------------------
# Missing keyword-only actual remains honestly Undischarged / binding gap
# ---------------------------------------------------------------------------


def test_missing_keyword_only_value_is_honestly_undischarged() -> None:
    """``helper([0], 0)`` — required keyword-only ``value`` absent.

    Call-time binding refuses before discharge; never fabricates a Completed
    store face. Gap is owned by SourceCallFrame.bind_actuals.
    """
    with pytest.raises(SugarNotWritten, match="missing required formal"):
        _call("[0], 0")


def test_missing_keyword_only_discrimination_not_completed() -> None:
    """Bite: missing value is refused by name; supplying value is the call."""
    _edge("[0], value=9")
    with pytest.raises(SugarNotWritten, match="missing required formal"):
        _call("[0], 0")


# ---------------------------------------------------------------------------
# Swapped-kind / coordinate twins fail
# ---------------------------------------------------------------------------


def test_positional_only_cannot_bind_as_keyword() -> None:
    """``helper(obj=[0], key=0, value=9)`` — pos-only obj refused as keyword."""
    with pytest.raises(SugarNotWritten, match="missing required formal"):
        _call("obj=[0], key=0, value=9")


def test_keyword_only_cannot_bind_as_positional() -> None:
    """``helper([0], 0, 9)`` — third positional is not keyword-only value."""
    with pytest.raises(SugarNotWritten, match="missing required formal"):
        _call("[0], 0, 9")


def test_swapped_kind_twins_discrimination() -> None:
    """Bite: illegal kinds are refused; legal kinds are the call."""
    _edge("[0], value=9")
    with pytest.raises(SugarNotWritten):
        _call("obj=[0], value=9")
    with pytest.raises(SugarNotWritten):
        _call("[0], 0, 9")


def test_swapped_key_value_coordinates_rejected() -> None:
    """Lying mint (index/value slots swapped) differs from truthful store."""
    function, truthful = _carrier()
    site = function.body[0].fragment
    obj_c, key_c, value_c = truthful.coordinates
    lying = NativeOperationExitCarrierV1.mint(
        site=site,
        operator="setitem",
        operands=(
            truthful.operands[0],
            truthful.operands[2],
            truthful.operands[1],
        ),
        coordinates=(obj_c, value_c, key_c),
    )
    actuals = {
        obj_c.coordinate_cid: fresh(
            ListValue, (TermValue(0), TermValue(1), TermValue(2))
        ),
        key_c.coordinate_cid: TermValue(1),
        value_c.coordinate_cid: TermValue(99),
    }
    t_face = truthful.discharge(None, actuals).exits[0]
    l_face = lying.discharge(None, actuals).exits[0]
    assert isinstance(t_face, Completed)
    t_list = _stored_list(t_face)
    assert t_list == fresh(ListValue, (TermValue(0), TermValue(99), TermValue(2)))
    if isinstance(l_face, Completed) and isinstance(l_face.value, UniverseValue):
        l_list = _stored_list(l_face)
        assert l_list != t_list
    elif isinstance(l_face, Completed) and isinstance(l_face.value, ListValue):
        assert l_face.value != t_list
    else:
        assert isinstance(l_face, Halted)
