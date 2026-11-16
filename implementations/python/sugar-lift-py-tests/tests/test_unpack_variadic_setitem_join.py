"""JOIN: unpack Name + formal setitem whose value is a variadic pack.

Concrete program:

    def f(a, i, p, *values):
        x, a[i] = p, values
        return x

Earlier Name binding (x ← p) survives later variadic-derived store halt:
when a[i] raises IndexError, the sole face is Halted with the block's state
kept — never a fabricated Completed return of x.

Success path: x returns as formal p; a[i] stores the authenticated TupleValue
packed from remaining positionals.

Since #8925 ``a`` above takes ``class:a`` as an input of ``f``'s contract (an
item store through an unpack leaf is read as ``a[i] = v`` is), so the store
is the dispatched ``__setitem__`` edge, ``call:dispatch:__setitem__(a, i,
values, py.class("0", class:a))``, owed with its halt kept and answered at
prove by the class each caller binds (#8864).

No item store waits on a caller's actual, so no ``setitem`` carrier stands
anywhere (#7757 step 7, ``store_effect_sugar.item_mutation``).  The same
unpack on a formal whose class is no input (``UNDECIDED_PROGRAM``: ``b = a``
reads ``a`` bare) is the undecided mutation, owed on both faces, its halt
kept with the block's state.  The list's own store faces (the pack stored at
the cell, the named ``IndexError`` at a bad index) are read where the
receiver is decided: the one item mutation on a ``ListValue`` actual, and the
same unpack on a list the frame built, the pack still the formal ``values``
(``DECIDED_PROGRAM`` / ``BAD_INDEX_PROGRAM``).
"""

from __future__ import annotations

import pytest

from frame_fresh import fresh
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
# the undecided mutation (``item_mutation``: nothing here decides its type).
UNDECIDED_PROGRAM = (
    "def f(a, i, p, *values):\n    b = a\n    x, b[i] = p, values\n    return x\n"
)

# The same unpack on a list the frame built: the receiver is decided, so the
# store is the list's own (``ListValue.setitem``) with the formal pack as its
# value, at a good and a bad index.
DECIDED_PROGRAM = (
    "def f(p, *values):\n    a = [0]\n    x, a[0] = p, values\n    return x\n"
)
BAD_INDEX_PROGRAM = (
    "def f(p, *values):\n    a = [0]\n    x, a[5] = p, values\n    return x\n"
)


def _tree(source: str, name: str = "unpack_variadic_setitem.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _desugared(source: str, name: str):
    """``source``'s one function alone and its own proof's reduction."""
    tree = _tree(source, name)
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _dispatched_helper():
    """``PROGRAM`` alone and its own proof's reduction: ``a``'s class is an
    input (#8925), so its unpack leaf store is the dispatched edge."""
    return _desugared(PROGRAM, "helper_alone.py")


def _undecided_helper():
    """``UNDECIDED_PROGRAM`` alone: the store is the undecided mutation."""
    return _desugared(UNDECIDED_PROGRAM, "helper_undecided_alone.py")


def _dispatched_call(outcome, method: str = "__setitem__"):
    """The dispatched store's coordinate ``call:dispatch:<method>(<receiver>,
    <operands>..., py.class("0", class:<receiver>))``, read off the one halt
    its edge owes (``python:raised(<call term>, <occurrence>)``)."""
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    assert isinstance(outcome, ExitSet), type(outcome)
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


def _undecided_store(outcome):
    """The undecided mutation (``item_mutation`` over a receiver whose type
    nothing here decides, ``undecided_item_mutation_faces``): no carrier and
    no dispatched edge; one undetermined halt owned by ``UndecidedSetitem``,
    kept with the block's state; every completed face under the store's own
    ``python:setitem.completes`` atom; both faces owing the undecided member
    (symbol ``None``).  Returns the halt and the completed faces."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    assert isinstance(outcome, ExitSet), type(outcome)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UndecidedSetitem"
    ]
    assert len(halts) == 1, outcome
    (halt,) = halts
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.state is not None
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    for face in (halt, *completed):
        assert None in {call.symbol for call in owed_calls(ExitSet((face,)))}
    for face in completed:
        assert "python:setitem.completes" in str(face.guard)
    assert "python:dispatch:__setitem__" not in {
        call.symbol for call in owed_calls(outcome)
    }
    assert outcome.completed_value() is None
    return halt, completed


def _floor_store(receiver, index, value):
    """The one item mutation on a receiver the lift decided (the ``ListValue``
    a caller hands ``a``): the list's own store, at the unpack's site."""
    from sugar_lift_py_tests.sugar.store_effect_sugar import item_mutation

    tree = _tree(UNDECIDED_PROGRAM, "floor_store_site.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    site = function.body[1].fragment
    return item_mutation("__setitem__", receiver, (index, value), site, None, unit=None)


def _call(actuals: str):
    """``f({actuals})`` in a caller's body, reduced alone.

    The call sits in a function body so its callee name reads ``f``'s
    ``def`` (``SourceUnit.function_definition_for_read``): a call the module
    body runs is answered as the module-level read is, not at all, the
    unanswered call (#9007 decision 1), and binds no actual to a formal."""
    tree = _tree(PROGRAM + f"\ndef caller():\n    return f({actuals})\n")
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def _sole_completed_universe(outcome) -> UniverseValue:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1, outcome
    face = outcome.exits[0]
    assert isinstance(face, Completed)
    assert isinstance(face.value, UniverseValue)
    return face.value


def _stored_list(outcome) -> ListValue:
    """The list the one item mutation completed with."""
    value = outcome.completed_value()
    assert isinstance(value, ListValue), outcome
    return value


def _returned(universe: UniverseValue) -> ReturnValue:
    returns = [s for s in universe.record.statements if isinstance(s, ReturnValue)]
    assert len(returns) == 1, returns
    return returns[0]


def _index_error(halted) -> None:
    """The floor's named ``IndexError`` at its authenticated locus."""
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


# ---------------------------------------------------------------------------
# Helper alone: the dispatched edge; value formal is *values
# ---------------------------------------------------------------------------


def test_helper_alone_retains_setitem_with_variadic_value() -> None:
    # Expected shape changed (#8925): on a formal whose class is an input the
    # unpack leaf store is the dispatched ``__setitem__`` edge, the pack its
    # value operand, in dispatch order; ``x`` binds ``p`` beside it, so every
    # completed face returns ``p``.
    from sugar_lift_py_tests.ir import str_const

    function, outcome = _dispatched_helper()
    call = _dispatched_call(outcome)
    assert [arg.name for arg in call.args[:3]] == ["a", "i", "values"]
    # p is a Name-binding formal, not a setitem operand.
    assert "p" not in [arg.name for arg in call.args[:3]]
    rides = call.args[-1]
    assert rides.name == "py.class", rides
    assert rides.args[0] == str_const("0")
    assert rides.args[1].name == "class:a", rides
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    for face in completed:
        assert isinstance(face.value, UniverseValue), face.value
        assert _returned(face.value).value.term.name == "p"
    kinds = {
        c.declared_name: c.parameter_kind for c in function.sugar().formal_coordinates
    }
    assert kinds["values"] == "variadic-positional"
    assert kinds["p"] == "positional-or-keyword"

    # Expected shape changed (#7757 step 7): on a formal whose class is no
    # input the store is the undecided mutation, never a ``setitem`` carrier
    # awaiting actuals; ``x`` still binds ``p`` on its completed face.
    _, undecided = _undecided_helper()
    _halt, undecided_completed = _undecided_store(undecided)
    for face in undecided_completed:
        assert isinstance(face.value, UniverseValue), face.value
        assert _returned(face.value).value.term.name == "p"
    # The carrier's projector is deleted: no item store is minted as one.


def test_helper_alone_is_not_completed_discrimination() -> None:
    _, dispatched = _dispatched_helper()
    assert dispatched.completed_value() is None
    assert dispatched.halts()
    _, undecided = _undecided_helper()
    with pytest.raises(AssertionError):
        assert undecided.completed_value() is not None
    with pytest.raises(AssertionError):
        assert not undecided.halts(), "the undecided store dropped its halt"
    with pytest.raises(AssertionError):
        assert isinstance(undecided, Completed)


# ---------------------------------------------------------------------------
# Success: Name x ← p survives; store packs *values
# ---------------------------------------------------------------------------


def test_mutable_receiver_completes_with_x_and_variadic_store() -> None:
    pack = TupleValue((TermValue(1), TermValue(2)))
    stored = _floor_store(fresh(ListValue, (TermValue(0),)), TermValue(0), pack)
    assert _stored_list(stored) == fresh(ListValue, (pack,))
    # The formal pack stored on a decided list: ``x`` returns ``p``.
    _, outcome = _desugared(DECIDED_PROGRAM, "decided_ok.py")
    universe = _sole_completed_universe(outcome)
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
    stored = _floor_store(
        fresh(ListValue, (TermValue(0),)), TermValue(0), TupleValue(())
    )
    assert _stored_list(stored) == fresh(ListValue, (TupleValue(()),))
    _, outcome = _desugared(DECIDED_PROGRAM, "decided_ok_empty.py")
    assert _returned(_sole_completed_universe(outcome)).value.term.name == "p"


# ---------------------------------------------------------------------------
# Halt: earlier Name binding survives; no fabricated completion
# ---------------------------------------------------------------------------


def test_variadic_store_halt_preserves_earlier_name_binding_state() -> None:
    """IndexError on a[i]=values; x←p is not rolled into a Completed return.

    The store of a pack on the list a caller hands ``a`` raises the named
    ``IndexError`` at index 5.  The same unpack on a list the frame built
    halts there with the block's record kept (``halts_at_statement_head``).
    Sole face is Halted — no fabricated completion of the return of x.
    """
    floor = _floor_store(
        fresh(ListValue, (TermValue(0),)), TermValue(5), TupleValue((TermValue(9),))
    )
    assert len(floor.exits) == 1
    _index_error(floor.exits[0])

    _, exits = _desugared(BAD_INDEX_PROGRAM, "decided_bad.py")
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    halted = exits.exits[0]
    _index_error(halted)
    assert halted.state is not None
    assert not isinstance(getattr(halted, "value", None), UniverseValue)
    assert all(isinstance(face, Halted) for face in exits.exits)


def test_source_caller_variadic_store_halt_no_fabricated_completion() -> None:
    # Expected verdict changed (#7757 steps 5 and 6, #8705): the source call
    # no longer is the one IndexError halt of the followed body; it is the
    # edge, which owes its halt, and its completed face is the call value,
    # never a completed return of ``x``.  The named IndexError with the
    # earlier binding's state is the list's own store at these actuals
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
    _, exits = _desugared(BAD_INDEX_PROGRAM, "decided_bad_d.py")
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Completed), "halted store completed the body"
    with pytest.raises(AssertionError):
        assert exits.exits[0].state is None, "halt dropped earlier-binding state"


# ---------------------------------------------------------------------------
# Twins: dispatch order ≠ eval order; no store waits on an actual
# ---------------------------------------------------------------------------


def test_swapped_source_discharge_order_twin_fails() -> None:
    _, outcome = _dispatched_helper()
    call = _dispatched_call(outcome)
    dispatch_names = tuple(arg.name for arg in call.args[:3])
    source_eval_names = ("values", "a", "i")  # value, receiver, index
    assert dispatch_names == ("a", "i", "values")
    assert dispatch_names != source_eval_names
    with pytest.raises(AssertionError):
        assert dispatch_names == source_eval_names


def test_undecided_receiver_store_is_owed_never_waiting_on_actuals() -> None:
    """No store waits on a caller's actual (#7757 step 7): where nothing
    decides the receiver's type the store of the pack is the undecided
    mutation, owing the undecided member on both faces, never a completed
    value (formerly a carrier left undischarged by a dropped pack, #7825)."""
    _, outcome = _undecided_helper()
    _undecided_store(outcome)
