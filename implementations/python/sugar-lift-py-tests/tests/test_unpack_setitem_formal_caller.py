"""JOIN CHECK: unpack assignment with formal setitem through a real caller.

Concrete program (post-#6630 setitem producer + #6604 Name+Subscript leaves):

    def f(a, i, p, q):
        x, a[i] = p, q
        return x

This is not a second setitem vertical and not a second unpack-leaf vertical.
It is the join: the unpack statement admits the subscript store leaf, formal
desugar mints the ``setitem`` demand (never a fabricated completion), and a
real caller / discharge supplies authenticated actuals.

The undischarged-carrier tooth for this helper alone already lives in
``test_assign_unpack_store_leaves.test_formal_subscript_unpack_desugar_stays_undischarged``
(#6634).  This module builds the caller/discharge faces on top of that tooth
and does not recreate it.

Operand order (setitem owner law):

  source evaluation:  value → receiver → index   (q, a, i for this body)
  discharge / mint:   receiver, index, value     (a, i, q for this body)

Acceptance faces (each with a discrimination twin):

  1. Helper alone retains the undischarged ``setitem`` demand in discharge
     order ``(receiver, index, value)`` — here ``(a, i, q)``.
  2. Mutable receiver completes with ``x`` bound to ``p`` and the correct
     list store at ``a[i]``.
  3. Invalid index yields named ``IndexError``; earlier name binding is not
     rolled back into a Completed face; the return statement does not complete.
  4. First-store halt blocks later targets (dual-store unpack).
  5. Swapped source/discharge order twin fails.

Since #8925 ``a`` above takes ``class:a`` as an input of ``f``'s contract: an
item store through an unpack leaf is read as ``a[i] = v`` is
(``nodes._receiver_uses``), so ``x, a[i] = p, q`` stores through the
dispatched ``__setitem__`` edge, ``call:dispatch:__setitem__(a, i, q,
py.class("0", class:a))``, owed with its halt kept and answered at prove by
the class each caller binds (``list.__setitem__``'s law, #8864).  The
``setitem`` carrier stands for the same unpack on a formal whose class is no
input; the discharge faces below read it off ``CARRIER_PROGRAM``, where
``b = a`` hands ``a`` on bare (``_receiver_uses``: blocked) and the store
goes through ``b``.

Does not touch ``store_effect_sugar``, projector tables, or carrier/ExitSet.
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
from sugar_lift_py_tests.floor import ListValue, ReturnValue, SymbolicValue, TermValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile

PROGRAM = "def f(a, i, p, q):\n    x, a[i] = p, q\n    return x\n"

# The same unpack on a formal whose class is no input of ``f``'s contract:
# ``b = a`` reads ``a`` bare, so the store through ``b`` (``a``'s object) is
# the ``setitem`` carrier over ``a``'s formal coordinate.
CARRIER_PROGRAM = "def f(a, i, p, q):\n    b = a\n    x, b[i] = p, q\n    return x\n"


def _tree(source: str, name: str = "unpack_setitem_caller.py") -> SourceFile:
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


def _class_input(call, receiver: str) -> None:
    """The receiver's class rides last: ``py.class("0", class:<receiver>)``."""
    from sugar_lift_py_tests.ir import str_const

    rides = call.args[-1]
    assert rides.name == "py.class", rides
    assert rides.args[0] == str_const("0")
    assert rides.args[1].name == f"class:{receiver}", rides


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
# 1. Helper alone retains setitem demand (discharge order)
# ---------------------------------------------------------------------------


def test_helper_alone_retains_setitem_demand_in_discharge_order() -> None:
    # Expected shape changed (#8925): ``x, a[i] = p, q`` on a formal whose
    # class is an input is the dispatched ``__setitem__`` edge, in the same
    # discharge order (receiver, index, value), owed with its halt and the
    # block's state kept; ``x`` binds ``p`` beside it, so every completed
    # face returns ``p``.  The carrier stands where the class is no input.
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

    _, pending = _helper()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"
    # Discharge order for this unpack: receiver a, index i, stored value q.
    # (Name target x binds p; p is not a setitem operand.)
    assert tuple(operand.term.name for operand in pending.operands) == (
        "a",
        "i",
        "q",
    )
    cids = pending.demand.operand_coordinate_cids
    assert len(cids) == 3
    assert all(cid is not None for cid in cids)
    assert len(set(cids)) == 3
    parameters = tuple(
        inspect.signature(_NATIVE_OPERATION_PROJECTORS["setitem"]).parameters
    )
    assert parameters == ("receiver", "index", "value", "site", "ctx")


def test_helper_alone_is_not_a_completed_face_discrimination() -> None:
    """Bite: undischarged formal unpack must not look like a Completed body."""
    _, dispatched = _dispatched_helper()
    assert dispatched.completed_value() is None
    assert dispatched.halts()
    _, pending = _helper()
    with pytest.raises(AssertionError):
        assert isinstance(pending, ExitSet) and pending.completed_value() is not None
    with pytest.raises(AssertionError):
        assert isinstance(pending, Completed)


# ---------------------------------------------------------------------------
# 2. Mutable receiver completes with x and the correct store
# ---------------------------------------------------------------------------


def test_mutable_receiver_completes_with_x_and_correct_store() -> None:
    _, pending = _helper()
    a_cid, i_cid, q_cid = pending.demand.operand_coordinate_cids
    universe = _completed_universe(
        pending,
        {
            a_cid: fresh(ListValue, (TermValue(0),)),
            i_cid: TermValue(0),
            q_cid: TermValue(9),
        },
    )
    # Correct store: a[0] becomes 9.
    assert _stored_list(universe) == fresh(ListValue, (TermValue(9),))
    # x bound to p: Name is spent as formal p; return carries SymbolicValue(p).
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
    joined at prove (#7757 step 7)."""
    from sugar_lift_py_tests.floor import CallSiteValue

    outcome = _call(actuals)
    assert isinstance(outcome, ExitSet)
    assert [face for face in outcome.exits if isinstance(face, Halted)], outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    assert isinstance(completed[0].value, CallSiteValue), completed[0].value
    return completed[0].value


def test_source_caller_mutable_receiver_completes() -> None:
    # Expected verdict changed (#8705, #8739): the call is the edge, two-faced
    # and owed; it no longer carries the callee's store on the caller's list.
    # The store itself is the row discharged with these actuals
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
    _, pending = _helper()
    a_cid, i_cid, q_cid = pending.demand.operand_coordinate_cids
    base = fresh(ListValue, (TermValue(0), TermValue(1)))
    at_zero = _completed_universe(
        pending, {a_cid: base, i_cid: TermValue(0), q_cid: TermValue(9)}
    )
    at_one = _completed_universe(
        pending, {a_cid: base, i_cid: TermValue(1), q_cid: TermValue(9)}
    )
    zero_list = _stored_list(at_zero)
    one_list = _stored_list(at_one)
    assert zero_list == fresh(ListValue, (TermValue(9), TermValue(1)))
    assert one_list == fresh(ListValue, (TermValue(0), TermValue(9)))
    with pytest.raises(AssertionError):
        assert zero_list == one_list


# ---------------------------------------------------------------------------
# 3. Invalid index → named IndexError; no statement completion
# ---------------------------------------------------------------------------


def test_invalid_index_named_indexerror_no_statement_completion() -> None:
    """IndexError from Floor setitem; return does not complete; not Completed.

    Post-#6644: the halt face carries the authentic reducer pre-effect state
    (earlier unpack binding seam).  Name ``x`` is spent by substitute so the
    block entries may be empty — the state object itself must still be present
    and must not be fabricated completion.
    """
    _, pending = _helper()
    assert pending.pre_effect_state is not None
    a_cid, i_cid, q_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        None,
        {
            a_cid: fresh(ListValue, (TermValue(0),)),
            i_cid: TermValue(5),
            q_cid: TermValue(9),
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
    # Authentic earlier-binding halt state (carrier #6640 / enrollment #6644).
    assert halted.state is not None
    assert pending.pre_effect_state.state is halted.state
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
    # binding's state is the row discharged with these actuals
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
    _, pending = _helper()
    a_cid, i_cid, q_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        None,
        {
            a_cid: fresh(ListValue, (TermValue(0),)),
            i_cid: TermValue(5),
            q_cid: TermValue(9),
        },
    )
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
# 5. Swapped source/discharge order twin fails
# ---------------------------------------------------------------------------


def test_swapped_source_discharge_order_twin_fails() -> None:
    """Discharge order is (a, i, q); source eval of the store is (q, a, i).

    A twin that equates the two orders must fail — the mint pins discharge
    order for the projector, not evaluation order.
    """
    _, pending = _helper()
    discharge_names = tuple(operand.term.name for operand in pending.operands)
    source_eval_names = ("q", "a", "i")  # value, receiver, index
    assert discharge_names == ("a", "i", "q")
    assert discharge_names != source_eval_names
    with pytest.raises(AssertionError):
        assert discharge_names == source_eval_names, "eval order is not discharge order"


def test_lying_swapped_index_value_mint_is_not_truthful_store() -> None:
    """Lying mint with index/value slots swapped is distinguishable."""
    function, truthful = _helper()
    # The unpack is ``CARRIER_PROGRAM``'s second statement.
    site = function.body[1].fragment
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
    truthful_universe = _completed_universe(truthful, actuals)
    truthful_list = _stored_list(truthful_universe)
    assert truthful_list == fresh(
        ListValue, (TermValue(0), TermValue(99), TermValue(2))
    )

    lying_exits = lying.discharge(None, actuals)
    lying_face = lying_exits.exits[0]
    if isinstance(lying_face, Completed) and isinstance(lying_face.value, ListValue):
        lying_list = lying_face.value
    elif isinstance(lying_face, Completed) and isinstance(
        lying_face.value, UniverseValue
    ):
        lying_list = _stored_list(lying_face.value)
    else:
        assert isinstance(lying_face, Halted)
        lying_list = None

    if lying_list is not None:
        assert lying_list != truthful_list
        with pytest.raises(AssertionError):
            assert lying_list == truthful_list, "swapped mint matched truthful store"


def test_missing_actuals_stay_undischarged() -> None:
    """Missing actuals: the store is the cited unanswered face (#7825)."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    _, pending = _helper()
    exits = pending.discharge(None, {})
    assert pending.unanswered_call() in owed_calls(exits)
    assert exits.completed_value() is None
