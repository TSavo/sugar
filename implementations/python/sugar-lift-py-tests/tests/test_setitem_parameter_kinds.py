"""Positional-only and keyword-only binding through formal setitem.

Concrete signature:

    def helper(obj, /, key=0, *, value):
        obj[key] = value

Binding kinds (SourceCallFrame.bind_actuals):

  - ``obj``  positional-only  — must be positional; keyword is refused
  - ``key``  positional-or-keyword with default 0 — default, pos, or kw
  - ``value`` keyword-only required — must be keyword; missing is honest gap

Helper alone remains Undischarged (``setattr``-style: setitem carrier).
Authenticated callers map actuals onto the exact native-operation formal
coordinates (obj, key, value) in discharge order. Mutable store completes;
invalid index yields named IndexError with exact pre-effect state.

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
    tree = _tree(HELPER, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


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
    assert isinstance(completed_face, Completed)
    record = getattr(completed_face.value, "record", None)
    assert record is not None
    lists = [s for s in record.statements if isinstance(s, ListValue)]
    assert len(lists) == 1, lists
    return lists[0]


# ---------------------------------------------------------------------------
# Helper alone → Undischarged setitem on exact formals
# ---------------------------------------------------------------------------


def test_helper_alone_is_undischarged_setitem_with_parameter_kinds() -> None:
    function, pending = _helper()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"
    assert tuple(value.term.name for value in pending.operands) == (
        "obj",
        "key",
        "value",
    )
    kinds = tuple(c.parameter_kind for c in function.sugar().formal_coordinates)
    assert kinds == ("positional-only", "positional-or-keyword", "keyword-only")
    # All three formals authenticate the setitem demand coordinates.
    assert pending.demand.operand_coordinate_cids == tuple(
        c.coordinate_cid for c in function.sugar().formal_coordinates
    )
    assert pending.pre_effect_state is not None
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
    assert edge.term.args[-1] == _named(edge, "py.kwarg", "value", 9)


def test_default_key_and_keyword_only_value_complete() -> None:
    """``helper([0], value=9)`` — key default 0 supplies the index formal,
    carried on the edge as ``py.default``."""
    edge = _edge("[0], value=9")
    assert edge.arg_values == (fresh(ListValue, (TermValue(0),)), TermValue(9))
    assert list(edge.term.args[1:]) == [
        _named(edge, "py.kwarg", "value", 9),
        _named(edge, "py.default", "key", 0),
    ]


def test_explicit_keyword_key_binds_same_key_formal() -> None:
    """``helper([0, 0], key=1, value=9)`` — key formal receives 1, store at 1.
    The edge names the formal ``key`` (``py.kwarg``); the frame's formal
    coordinate cids the followed call carried are gone with the follow
    (#8705, #8751): prove binds by name."""
    edge = _edge("[0, 0], key=1, value=9")
    assert edge.arg_values[1] == TermValue(1)
    assert edge.arg_values[2] == TermValue(9)
    assert list(edge.term.args[1:]) == [
        _named(edge, "py.kwarg", "key", 1),
        _named(edge, "py.kwarg", "value", 9),
    ]


def test_callers_bind_to_exact_native_operation_coordinates() -> None:
    """Direct discharge uses the same formal cids as the setitem demand."""
    function, pending = _helper()
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
    _, pending = _helper()
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
    _, pending = _helper()
    assert pending.pre_effect_state is not None
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
    assert halted.state is not None
    assert pending.pre_effect_state.state is halted.state
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
    _, pending = _helper()
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
    with pytest.raises(AssertionError):
        assert exits.exits[0].state is None


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
    function, truthful = _helper()
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
