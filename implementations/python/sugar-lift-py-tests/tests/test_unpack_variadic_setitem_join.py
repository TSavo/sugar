"""JOIN: unpack Name + formal setitem whose value is a variadic pack.

Concrete program:

    def f(a, i, p, *values):
        x, a[i] = p, values
        return x

Earlier Name binding (x ← p) survives later variadic-derived store halt:
when a[i] raises IndexError, the sole face is Halted with exact
pre_effect_state identity — never a fabricated Completed return of x.

Success path: x returns as formal p; a[i] stores the authenticated TupleValue
packed from remaining positionals.

Since #8925 ``a`` above takes ``class:a`` as an input of ``f``'s contract (an
item store through an unpack leaf is read as ``a[i] = v`` is), so the store
is the dispatched ``__setitem__`` edge, ``call:dispatch:__setitem__(a, i,
values, py.class("0", class:a))``, owed with its halt kept and answered at
prove by the class each caller binds (#8864).  The ``setitem`` carrier stands
for the same unpack on a formal whose class is no input; the discharge faces
below read it off ``CARRIER_PROGRAM`` (``b = a`` reads ``a`` bare).

Does not touch carrier/ExitSet, store producer/projector/Floor; no second binder.
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
from sugar_lift_py_tests.floor import (
    ListValue,
    ReturnValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile

PROGRAM = "def f(a, i, p, *values):\n    x, a[i] = p, values\n    return x\n"

# The same unpack on a formal whose class is no input of ``f``'s contract:
# ``b = a`` reads ``a`` bare, so the store through ``b`` (``a``'s object) is
# the ``setitem`` carrier over ``a``'s formal coordinate.
CARRIER_PROGRAM = (
    "def f(a, i, p, *values):\n    b = a\n    x, b[i] = p, values\n    return x\n"
)


def _tree(source: str, name: str = "unpack_variadic_setitem.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _dispatched_helper():
    """``PROGRAM`` alone and its own proof's reduction: ``a``'s class is an
    input (#8925), so its unpack leaf store is the dispatched edge."""
    tree = _tree(PROGRAM, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _helper():
    """``CARRIER_PROGRAM`` alone: the undischarged ``setitem`` carrier, with
    the pre-effect state the body's reducer enrolls."""
    tree = _tree(CARRIER_PROGRAM, "helper_carrier_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _dispatched_call(outcome, method: str = "__setitem__"):
    """The dispatched store's coordinate ``call:dispatch:<method>(<receiver>,
    <operands>..., py.class("0", class:<receiver>))``, read off the one halt
    its edge owes (``python:raised(<call term>, <occurrence>)``)."""
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
    assert halts[0].state is not None
    assert f"python:dispatch:{method}" in {
        call.symbol for call in owed_calls(outcome)
    }
    raised = halts[0].effect.raised_by_call
    assert raised.name == "python:raised", raised
    call = raised.args[0]
    assert call.name == call_symbol(f"dispatch:{method}"), call
    return call


def _call(actuals: str):
    tree = _tree(PROGRAM + f"\nf({actuals})\n")
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def _completed_universe(pending, actuals) -> UniverseValue:
    exits = pending.discharge(None, actuals)
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    face = exits.exits[0]
    assert isinstance(face, Completed)
    assert isinstance(face.value, UniverseValue)
    return face.value


def _stored_list(universe: UniverseValue) -> ListValue:
    lists = [s for s in universe.record.statements if isinstance(s, ListValue)]
    assert len(lists) == 1, lists
    return lists[0]


def _returned(universe: UniverseValue) -> ReturnValue:
    returns = [s for s in universe.record.statements if isinstance(s, ReturnValue)]
    assert len(returns) == 1, returns
    return returns[0]


# ---------------------------------------------------------------------------
# Helper alone: setitem demand; value formal is *values
# ---------------------------------------------------------------------------


def test_helper_alone_retains_setitem_with_variadic_value() -> None:
    # Expected shape changed (#8925): on a formal whose class is an input the
    # unpack leaf store is the dispatched ``__setitem__`` edge, the pack its
    # value operand, in discharge order; ``x`` binds ``p`` beside it, so
    # every completed face returns ``p``.  The carrier stands where the class
    # is no input.
    from sugar_lift_py_tests.ir import str_const

    _, outcome = _dispatched_helper()
    call = _dispatched_call(outcome)
    assert [arg.name for arg in call.args[:3]] == ["a", "i", "values"]
    rides = call.args[-1]
    assert rides.name == "py.class", rides
    assert rides.args[0] == str_const("0")
    assert rides.args[1].name == "class:a", rides
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    for face in completed:
        assert isinstance(face.value, UniverseValue), face.value
        assert _returned(face.value).value.term.name == "p"

    function, pending = _helper()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"
    assert tuple(operand.term.name for operand in pending.operands) == (
        "a",
        "i",
        "values",
    )
    kinds = {
        c.declared_name: c.parameter_kind for c in function.sugar().formal_coordinates
    }
    assert kinds["values"] == "variadic-positional"
    assert kinds["p"] == "positional-or-keyword"
    # p is a Name-binding formal, not a setitem operand.
    setitem_cids = set(pending.demand.operand_coordinate_cids)
    p_cid = next(
        c.coordinate_cid
        for c in function.sugar().formal_coordinates
        if c.declared_name == "p"
    )
    assert p_cid not in setitem_cids
    parameters = tuple(
        inspect.signature(_NATIVE_OPERATION_PROJECTORS["setitem"]).parameters
    )
    assert parameters == ("receiver", "index", "value", "site", "ctx")


def test_helper_alone_is_not_completed_discrimination() -> None:
    _, dispatched = _dispatched_helper()
    assert dispatched.completed_value() is None
    assert dispatched.halts()
    _, pending = _helper()
    with pytest.raises(AssertionError):
        assert isinstance(pending, ExitSet) and pending.completed_value() is not None
    with pytest.raises(AssertionError):
        assert isinstance(pending, Completed)


# ---------------------------------------------------------------------------
# Success: Name x ← p survives; store packs *values
# ---------------------------------------------------------------------------


def test_mutable_receiver_completes_with_x_and_variadic_store() -> None:
    _, pending = _helper()
    a_cid, i_cid, values_cid = pending.demand.operand_coordinate_cids
    pack = TupleValue((TermValue(1), TermValue(2)))
    universe = _completed_universe(
        pending,
        {
            a_cid: fresh(ListValue, (TermValue(0),)),
            i_cid: TermValue(0),
            values_cid: pack,
        },
    )
    assert _stored_list(universe) == fresh(ListValue, (pack,))
    returned = _returned(universe)
    assert isinstance(returned.value, SymbolicValue)
    assert returned.value.term.name == "p"
    post = str(universe.post())
    assert "out" in post and "p" in post


def _the_call(actuals: str):
    """The source call's value on its completed face: a same-file call is
    its coordinate and edge, joined at prove (#7757 steps 5 and 6, #8705),
    owing its halt under the complement of its ``completes`` atom.  Its
    ``arg_values`` are the actuals as written; the one binder's packing of
    ``*values`` is on its term, every formal by name (``py.kwarg``, the
    variadic ``py.packed``)."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.outcome.exit_set import complement_guard

    outcome = _call(actuals)
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(halted) == 1 and len(completed) == 1, outcome
    # The caller's halt is the edge's halted face: under the complement of
    # the call's ``completes`` atom, naming no exception here -- prove types
    # it by the helper's contract, whose row states the IndexError locus.
    assert completed[0].guard.name == "python:unknown_callee_call.completes"
    assert halted[0].guard == complement_guard(completed[0].guard)
    assert halted[0].effect.exception_type_coordinate is None
    assert isinstance(completed[0].value, CallSiteValue), completed[0].value
    return completed[0].value


def _coordinate(call):
    """The call's coordinate ``call:<target>(<arguments>)``: the completed
    face of the one unanswered call returns ``python:call_result(<call
    term>, <occurrence>)`` (#7757 steps 5 and 6, #8705), so the formals the
    one binder packs are the call term's arguments, never the result's."""
    result = call.term
    assert result.name == "python:call_result", result
    coordinate = result.args[0]
    assert coordinate.name.startswith("call:"), coordinate
    return coordinate


def _formal(call, name: str, value):
    """A parameter ``name`` by name, ``py.kwarg``; the helper's variadic
    ``values`` as the packed value it stands as, ``py.packed`` (a keyword
    naming it would go into ``**kwargs``, never bind it)."""
    from sugar_lift_py_tests.ir import ctor, str_const

    form = "py.packed" if name == "values" else "py.kwarg"
    return ctor(form, [str_const(name), value.to_term(owner=str(call.site))])


def _classes() -> list:
    """After the formals ride the classes the caller decides, each keyed by
    its formal's name where the signature packs (#8857,
    ``definition_edge_call``): the ``[0]`` it built a ``list``, ``i`` and
    ``p`` each an ``int``, the pack a ``tuple``.  (Since #8925 ``a``,
    stored into through an unpack target, takes ``class:a``, which the
    ``list`` binds at prove; the caller supplies the classes whatever the
    callee's contract takes.)"""
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.receiver_dispatch import (
        CLASS_ARGUMENT,
        builtin_class_term,
    )

    return [
        ctor(CLASS_ARGUMENT, [str_const(key), builtin_class_term(name)])
        for key, name in (
            ("a", "list"),
            ("i", "int"),
            ("p", "int"),
            ("values", "tuple"),
        )
    ]


def test_source_caller_packs_remaining_positionals_into_values() -> None:
    call = _the_call("[0], 0, 7, 1, 2")
    assert call.arg_values == (
        fresh(ListValue, (TermValue(0),)),
        TermValue(0),
        TermValue(7),
        TermValue(1),
        TermValue(2),
    )
    assert list(_coordinate(call).args[1:]) == [
        _formal(call, "i", TermValue(0)),
        _formal(call, "p", TermValue(7)),
        _formal(call, "values", TupleValue((TermValue(1), TermValue(2)))),
        *_classes(),
    ]


def test_empty_variadic_store_is_honest_empty_tuple() -> None:
    _, pending = _helper()
    a_cid, i_cid, values_cid = pending.demand.operand_coordinate_cids
    universe = _completed_universe(
        pending,
        {
            a_cid: fresh(ListValue, (TermValue(0),)),
            i_cid: TermValue(0),
            values_cid: TupleValue(()),
        },
    )
    assert _stored_list(universe) == fresh(ListValue, (TupleValue(()),))
    assert _returned(universe).value.term.name == "p"


# ---------------------------------------------------------------------------
# Halt: earlier Name binding survives; no fabricated completion
# ---------------------------------------------------------------------------


def test_variadic_store_halt_preserves_earlier_name_binding_state() -> None:
    """IndexError on a[i]=values; x←p is not rolled into a Completed return.

    Post-#6644: halt face carries pending.pre_effect_state.state identity.
    Sole face is Halted — no fabricated completion of the return of x.
    """
    _, pending = _helper()
    assert pending.pre_effect_state is not None
    a_cid, i_cid, values_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        None,
        {
            a_cid: fresh(ListValue, (TermValue(0),)),
            i_cid: TermValue(5),
            values_cid: TupleValue((TermValue(9),)),
        },
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
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
    assert all(isinstance(face, Halted) for face in exits.exits)


def test_source_caller_variadic_store_halt_no_fabricated_completion() -> None:
    # Expected verdict changed (#7757 steps 5 and 6, #8705): the source call
    # no longer is the one IndexError halt of the followed body; it is the
    # edge, which owes its halt, and its completed face is the call value,
    # never a completed return of ``x``.  The named IndexError with the
    # earlier binding's state is the row discharged with these actuals
    # (``test_variadic_store_halt_preserves_earlier_name_binding_state``),
    # joined at the call by prove (#8690, #8749).
    call = _the_call("[0], 5, 7, 1, 2")
    assert not isinstance(call, UniverseValue)
    assert list(_coordinate(call).args[1:]) == [
        _formal(call, "i", TermValue(5)),
        _formal(call, "p", TermValue(7)),
        _formal(call, "values", TupleValue((TermValue(1), TermValue(2)))),
        *_classes(),
    ]


def test_halt_discrimination_is_not_completed_return_of_x() -> None:
    """Bite: store halt must not present Completed with return of p/x."""
    _, pending = _helper()
    a_cid, i_cid, values_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        None,
        {
            a_cid: fresh(ListValue, (TermValue(0),)),
            i_cid: TermValue(5),
            values_cid: TupleValue((TermValue(9),)),
        },
    )
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Completed), "halted store completed the body"
    with pytest.raises(AssertionError):
        assert exits.exits[0].state is None, "halt dropped earlier-binding state"


# ---------------------------------------------------------------------------
# Twins: discharge order ≠ eval order; dropped pack undischarged
# ---------------------------------------------------------------------------


def test_swapped_source_discharge_order_twin_fails() -> None:
    _, pending = _helper()
    discharge_names = tuple(operand.term.name for operand in pending.operands)
    source_eval_names = ("values", "a", "i")  # value, receiver, index
    assert discharge_names == ("a", "i", "values")
    assert discharge_names != source_eval_names
    with pytest.raises(AssertionError):
        assert discharge_names == source_eval_names


def test_dropped_variadic_pack_is_undischarged() -> None:
    """The dropped pack leaves the store the cited unanswered face (#7825)."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    _, pending = _helper()
    a_cid, i_cid, _values_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        None,
        {
            a_cid: fresh(ListValue, (TermValue(0),)),
            i_cid: TermValue(0),
        },
    )
    assert pending.unanswered_call() in owed_calls(exits)
    assert exits.completed_value() is None
