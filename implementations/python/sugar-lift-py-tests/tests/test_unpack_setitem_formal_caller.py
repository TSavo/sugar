"""JOIN CHECK: unpack assignment with formal setitem through a real caller.

Concrete program (post-#6630 setitem producer + #6604 Name+Subscript leaves):

    def f(a, i, p, q):
        x, a[i] = p, q
        return x

This is not a second setitem vertical and not a second unpack-leaf vertical.
It is the join: the unpack statement admits the subscript store leaf, its
store goes through the one item mutation (``item_mutation`` of
``store_effect_sugar``, #7757 step 7) -- never a fabricated completion -- and
a real caller's call is its coordinate and edge, joined at prove.

Operand order (setitem owner law):

  source evaluation:  value → receiver → index   (q, a, i for this body)
  dispatch:           receiver, index, value     (a, i, q for this body)

Since #8925 ``a`` above takes ``class:a`` as an input of ``f``'s contract: an
item store through an unpack leaf is read as ``a[i] = v`` is
(``nodes._receiver_uses``), so ``x, a[i] = p, q`` stores through the
dispatched ``__setitem__`` edge, ``call:dispatch:__setitem__(a, i, q,
py.class("0", class:a))``, owed with its halt kept and answered at prove by
the class each caller binds (``list.__setitem__``'s law, #8864).

No item store waits on a caller's actual, so no ``setitem`` carrier stands
anywhere (#7757 step 7).  The same unpack on a formal whose class is no input
(``UNDECIDED_PROGRAM``: ``b = a`` hands ``a`` on bare, ``_receiver_uses``:
blocked) is the undecided mutation: it completes under its own
``python:setitem.completes`` atom or raises something undetermined, both
faces owing the undecided member, the halt kept with the block's state.  The
floor's own store faces that a caller's list decides (the store at the right
cell, the named ``IndexError`` at a bad index) are read where the receiver is
decided: the one item mutation on a ``ListValue`` actual, and the same unpack
on a list the frame built (``DECIDED_PROGRAM`` / ``BAD_INDEX_PROGRAM``).

Acceptance faces (each with a discrimination twin):

  1. Helper alone: the dispatched edge in order ``(receiver, index, value)``
     -- here ``(a, i, q)``; on a formal whose class is no input, the
     undecided mutation, owed, halt kept.
  2. Mutable receiver completes with ``x`` bound to ``p`` and the correct
     list store at ``a[i]``.
  3. Invalid index yields named ``IndexError``; earlier name binding is not
     rolled back into a Completed face; the return statement does not complete.
  4. First-store halt blocks later targets (dual-store unpack).
  5. Swapped source/dispatch order twin fails.
"""

from __future__ import annotations

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ListValue, ReturnValue, SymbolicValue, TermValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile

PROGRAM = "def f(a, i, p, q):\n    x, a[i] = p, q\n    return x\n"

# The same unpack on a formal whose class is no input of ``f``'s contract:
# ``b = a`` reads ``a`` bare, so the store through ``b`` (``a``'s object) is
# the undecided mutation (``item_mutation``: nothing here decides its type).
UNDECIDED_PROGRAM = "def f(a, i, p, q):\n    b = a\n    x, b[i] = p, q\n    return x\n"

# The same unpack on a list the frame built: the receiver is decided, so the
# store is the list's own (``ListValue.setitem``), at a good and a bad index.
DECIDED_PROGRAM = "def f(p):\n    a = [0]\n    x, a[0] = p, 9\n    return x\n"
BAD_INDEX_PROGRAM = "def f(p):\n    a = [0]\n    x, a[5] = p, 9\n    return x\n"


def _tree(source: str, name: str = "unpack_setitem_caller.py") -> SourceFile:
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


def _class_input(call, receiver: str) -> None:
    """The receiver's class rides last: ``py.class("0", class:<receiver>)``."""
    from sugar_lift_py_tests.ir import str_const

    rides = call.args[-1]
    assert rides.name == "py.class", rides
    assert rides.args[0] == str_const("0")
    assert rides.args[1].name == f"class:{receiver}", rides


def _undecided_store(outcome):
    """The undecided mutation (``item_mutation`` over a receiver whose type
    nothing here decides, ``undecided_item_mutation_faces``): no carrier and
    no dispatched edge; one undetermined halt owned
    by ``UndecidedSetitem``, kept with the block's state; every completed
    face under the store's own ``python:setitem.completes`` atom; both faces
    owing the undecided member (symbol ``None``).  Returns the halt and the
    completed faces."""
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
    tree = _tree(PROGRAM + f"\nf({actuals})\n")
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
# 1. Helper alone: the dispatched edge in dispatch order; the undecided store
# ---------------------------------------------------------------------------


def test_helper_alone_retains_setitem_demand_in_discharge_order() -> None:
    # Expected shape changed (#8925): ``x, a[i] = p, q`` on a formal whose
    # class is an input is the dispatched ``__setitem__`` edge, in dispatch
    # order (receiver, index, value), owed with its halt and the block's state
    # kept; ``x`` binds ``p`` beside it, so every completed face returns ``p``.
    _, outcome = _dispatched_helper()
    call = _dispatched_call(outcome)
    assert [arg.name for arg in call.args[:3]] == ["a", "i", "q"]
    _class_input(call, "a")
    assert len(call.args) == 4
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    for face in completed:
        assert isinstance(face.value, UniverseValue), face.value
        returned = _returned(face.value)
        assert isinstance(returned.value, SymbolicValue)
        assert returned.value.term.name == "p"

    # Expected shape changed (#7757 step 7): on a formal whose class is no
    # input the store is the undecided mutation, never a ``setitem`` carrier
    # awaiting actuals; ``x`` still binds ``p`` on its completed face.
    _, undecided = _undecided_helper()
    _halt, undecided_completed = _undecided_store(undecided)
    for face in undecided_completed:
        assert isinstance(face.value, UniverseValue), face.value
        returned = _returned(face.value)
        assert isinstance(returned.value, SymbolicValue)
        assert returned.value.term.name == "p"
    # The carrier's projector is deleted: no item store is minted as one.


def test_helper_alone_is_not_a_completed_face_discrimination() -> None:
    """Bite: the formal unpack's store must not look like a Completed body."""
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
# 2. Mutable receiver completes with x and the correct store
# ---------------------------------------------------------------------------


def test_mutable_receiver_completes_with_x_and_correct_store() -> None:
    # Correct store: the list a caller hands ``a``, ``a[0] = 9``, becomes
    # ``[9]`` (the one item mutation's floor store; no carrier discharges).
    stored = _floor_store(fresh(ListValue, (TermValue(0),)), TermValue(0), TermValue(9))
    assert _stored_list(stored) == fresh(ListValue, (TermValue(9),))
    # x bound to p beside the decided store: the return carries
    # SymbolicValue(p).
    _, outcome = _desugared(DECIDED_PROGRAM, "decided_ok.py")
    universe = _sole_completed_universe(outcome)
    returned = _returned(universe)
    assert isinstance(returned.value, SymbolicValue)
    assert returned.value.term.name == "p"
    # Post formula is out = p (x survived into the return).
    post = str(universe.post())
    assert "out" in post and "p" in post


def _the_call(actuals: str):
    """The source call's value on its completed face.  A same-file call is
    its coordinate and edge, joined at prove (#7757 steps 5 and 6, #8705):
    it completes under its ``completes`` atom and owes its halt under the
    complement; the helper's store on the caller's list is no longer carried
    out of its frame (``caller_visible_values``, deleted by #8739) and is
    joined at prove (#7757 step 7).  Its completed value carries its record
    that it may reach every module global (#9108,
    ``call_site_value.bind_after_call``); the call is the value beneath it."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.floor.call_site_value import AfterCallRecordValue
    from sugar_lift_py_tests.floor.named_expression_value import (
        peel_walrus_binds,
    )

    outcome = _call(actuals)
    assert isinstance(outcome, ExitSet)
    assert [face for face in outcome.exits if isinstance(face, Halted)], outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    binds, value = peel_walrus_binds(completed[0].value)
    assert any(
        isinstance(bind.assigned_value, AfterCallRecordValue)
        and bind.assigned_value.reaches_every_global()
        for bind in binds
    ), binds
    assert isinstance(value, CallSiteValue), value
    return value


def test_source_caller_mutable_receiver_completes() -> None:
    # Expected verdict changed (#8705, #8739): the call is the edge, two-faced
    # and owed; it no longer carries the callee's store on the caller's list.
    # The store on these actuals is the list's own
    # (``test_mutable_receiver_completes_with_x_and_correct_store``).
    presented = _the_call("[0], 0, 1, 9")
    # The edge carries the actuals for a, i, p, q as written.
    assert presented.arg_values == (
        fresh(ListValue, (TermValue(0),)),
        TermValue(0),
        TermValue(1),
        TermValue(9),
    )


def test_mutable_receiver_completes_discrimination_wrong_cell() -> None:
    """Bite: storing at index 0 is not the same face as storing at index 1."""
    base = fresh(ListValue, (TermValue(0), TermValue(1)))
    zero_list = _stored_list(_floor_store(base, TermValue(0), TermValue(9)))
    one_list = _stored_list(_floor_store(base, TermValue(1), TermValue(9)))
    assert zero_list == fresh(ListValue, (TermValue(9), TermValue(1)))
    assert one_list == fresh(ListValue, (TermValue(0), TermValue(9)))
    with pytest.raises(AssertionError):
        assert zero_list == one_list


# ---------------------------------------------------------------------------
# 3. Invalid index → named IndexError; no statement completion
# ---------------------------------------------------------------------------


def test_invalid_index_named_indexerror_no_statement_completion() -> None:
    """IndexError from Floor setitem; return does not complete; not Completed.

    The store on the list a caller hands ``a`` raises the named
    ``IndexError`` at index 5.  The same unpack on a list the frame built
    halts there too, with the record the reducer gives the halt (the block's
    state before the store, ``halts_at_statement_head``): ``x`` is spent by
    substitute so the block entries may be empty -- the state object itself
    must still be present and must not be fabricated completion.
    """
    floor = _floor_store(fresh(ListValue, (TermValue(0),)), TermValue(5), TermValue(9))
    assert len(floor.exits) == 1
    _index_error(floor.exits[0])

    _, exits = _desugared(BAD_INDEX_PROGRAM, "decided_bad.py")
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    halted = exits.exits[0]
    _index_error(halted)
    # Authentic earlier-binding halt state: the block's record, kept.
    assert halted.state is not None
    # No statement completion: no UniverseValue return face on the halt arm.
    assert not isinstance(getattr(halted, "value", None), UniverseValue)
    # Earlier name binding is not rolled back into a fake Completed — the sole
    # face is the store halt. The success twin (above) is the artifact that
    # x maps to p; halt must not claim the body completed.
    assert all(isinstance(face, Halted) for face in exits.exits)


def test_source_caller_invalid_index_named_indexerror() -> None:
    # Expected verdict changed (#7757 steps 5 and 6, #8705): the source call
    # no longer is the followed body's one IndexError halt.  It is the edge,
    # which owes its halt and completes with the call value, never a
    # completed return of ``x``; the named IndexError with the earlier
    # binding's state is the list's own store at these actuals
    # (``test_invalid_index_named_indexerror_no_statement_completion``),
    # joined at the call by prove (#8690, #8749).
    presented = _the_call("[0], 5, 1, 9")
    assert not isinstance(presented, UniverseValue)
    assert presented.arg_values == (
        fresh(ListValue, (TermValue(0),)),
        TermValue(5),
        TermValue(1),
        TermValue(9),
    )


def test_invalid_index_discrimination_is_not_completed() -> None:
    """Bite: IndexError face must not be misread as Completed with x."""
    _, exits = _desugared(BAD_INDEX_PROGRAM, "decided_bad_d.py")
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Completed), "halted store completed the body"
    # Bite: missing earlier-binding state is also not the law.
    with pytest.raises(AssertionError):
        assert exits.exits[0].state is None, "halt dropped earlier-binding state"


# ---------------------------------------------------------------------------
# 4. First-store halt blocks later targets
# ---------------------------------------------------------------------------


def test_first_store_halt_blocks_later_targets() -> None:
    """``a[0], b[0] = 2, 3`` with b immutable: first store ran; no completion."""
    source = (
        "def f():\n"
        "    a = [0]\n"
        "    b = (1,)\n"
        "    a[0], b[0] = 2, 3\n"
        "    return a\n"
    )
    tree = _tree(source, "dual_partial.py")
    fn = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    outcome = fn.sugar().desugar(None)
    halted = [e for e in outcome.exits if isinstance(e, Halted)]
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    assert len(halted) == 1
    assert len(completed) == 0
    assert halted[0].effect.exception_name == "TypeError"
    assert halted[0].effect.producer_node_owner == "TupleValue.setitem"
    # Later return target did not complete — sole face is the second-store halt.


def test_first_store_halt_blocks_later_targets_discrimination() -> None:
    """Bite: partial dual-store must not present a sole Completed arm."""
    source = (
        "def f():\n"
        "    a = [0]\n"
        "    b = (1,)\n"
        "    a[0], b[0] = 2, 3\n"
        "    return a\n"
    )
    tree = _tree(source, "dual_partial_d.py")
    fn = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    outcome = fn.sugar().desugar(None)
    with pytest.raises(AssertionError):
        assert len(outcome.exits) == 1 and isinstance(
            outcome.exits[0], Completed
        ), "later target ran after first-store halt"


# ---------------------------------------------------------------------------
# 5. Swapped source/dispatch order twin fails
# ---------------------------------------------------------------------------


def test_swapped_source_discharge_order_twin_fails() -> None:
    """Dispatch order is (a, i, q); source eval of the store is (q, a, i).

    A twin that equates the two orders must fail — the dispatched edge pins
    ``type(a).__setitem__(a, i, q)``'s order, not evaluation order.
    """
    _, outcome = _dispatched_helper()
    call = _dispatched_call(outcome)
    dispatch_names = tuple(arg.name for arg in call.args[:3])
    source_eval_names = ("q", "a", "i")  # value, receiver, index
    assert dispatch_names == ("a", "i", "q")
    assert dispatch_names != source_eval_names
    with pytest.raises(AssertionError):
        assert dispatch_names == source_eval_names, "eval order is not dispatch order"


def test_lying_swapped_index_value_mint_is_not_truthful_store() -> None:
    """A store with index/value swapped is distinguishable: the truthful one
    stores 99 at 1; the swapped one stores 1 at 99, the named IndexError."""
    base = fresh(ListValue, (TermValue(0), TermValue(1), TermValue(2)))
    truthful_list = _stored_list(_floor_store(base, TermValue(1), TermValue(99)))
    assert truthful_list == fresh(
        ListValue, (TermValue(0), TermValue(99), TermValue(2))
    )

    lying = _floor_store(base, TermValue(99), TermValue(1))
    assert len(lying.exits) == 1
    _index_error(lying.exits[0])
    with pytest.raises(AssertionError):
        assert lying.completed_value() == truthful_list, "swapped store matched"


def test_missing_actuals_stay_undischarged() -> None:
    """No store waits on a caller's actual (#7757 step 7): where nothing
    decides the receiver's type the store is the undecided mutation, owing
    the undecided member on both faces, never a completed value."""
    _, outcome = _undecided_helper()
    _undecided_store(outcome)
