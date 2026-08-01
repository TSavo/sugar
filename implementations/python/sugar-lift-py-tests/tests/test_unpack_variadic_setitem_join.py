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

Does not touch carrier/ExitSet, store producer/projector/Floor; no second binder.
"""

from __future__ import annotations

import inspect

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ListValue, ReturnValue, SymbolicValue, TermValue, TupleValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile

PROGRAM = "def f(a, i, p, *values):\n    x, a[i] = p, values\n    return x\n"


def _tree(source: str, name: str = "unpack_variadic_setitem.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper():
    tree = _tree(PROGRAM, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


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
    exits = pending.discharge(actuals)
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
    assert parameters == ("receiver", "index", "value", "site")


def test_helper_alone_is_not_completed_discrimination() -> None:
    _, pending = _helper()
    with pytest.raises(AssertionError):
        assert isinstance(pending, Complete)
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
            a_cid: ListValue((TermValue(0),)),
            i_cid: TermValue(0),
            values_cid: pack,
        },
    )
    assert _stored_list(universe) == ListValue((pack,))
    returned = _returned(universe)
    assert isinstance(returned.value, SymbolicValue)
    assert returned.value.term.name == "p"
    post = str(universe.post())
    assert "out" in post and "p" in post


def test_source_caller_packs_remaining_positionals_into_values() -> None:
    outcome = _call("[0], 0, 7, 1, 2")
    assert isinstance(outcome, ExitSet)
    face = outcome.exits[0]
    assert isinstance(face, Completed)
    assert face.value.arg_values == (
        ListValue((TermValue(0),)),
        TermValue(0),
        TermValue(7),
        TupleValue((TermValue(1), TermValue(2))),
    )
    assert face.value.parameters == ("a", "i", "p", "values")


def test_empty_variadic_store_is_honest_empty_tuple() -> None:
    _, pending = _helper()
    a_cid, i_cid, values_cid = pending.demand.operand_coordinate_cids
    universe = _completed_universe(
        pending,
        {
            a_cid: ListValue((TermValue(0),)),
            i_cid: TermValue(0),
            values_cid: TupleValue(()),
        },
    )
    assert _stored_list(universe) == ListValue((TupleValue(()),))
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
        {
            a_cid: ListValue((TermValue(0),)),
            i_cid: TermValue(5),
            values_cid: TupleValue((TermValue(9),)),
        }
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert not isinstance(halted, Completed)
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert isinstance(halted.effect.occurrence_id, str) and ":" in halted.effect.occurrence_id, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    assert halted.state is not None
    assert pending.pre_effect_state.state is halted.state
    assert not isinstance(getattr(halted, "value", None), UniverseValue)
    assert all(isinstance(face, Halted) for face in exits.exits)


def test_source_caller_variadic_store_halt_no_fabricated_completion() -> None:
    outcome = _call("[0], 5, 7, 1, 2")
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert halted.state is not None
    assert not isinstance(getattr(halted, "value", None), UniverseValue)


def test_halt_discrimination_is_not_completed_return_of_x() -> None:
    """Bite: store halt must not present Completed with return of p/x."""
    _, pending = _helper()
    a_cid, i_cid, values_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            a_cid: ListValue((TermValue(0),)),
            i_cid: TermValue(5),
            values_cid: TupleValue((TermValue(9),)),
        }
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
    from sugar_source_tree.panic import SugarNotWritten

    _, pending = _helper()
    a_cid, i_cid, _values_cid = pending.demand.operand_coordinate_cids
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge(
            {
                a_cid: ListValue((TermValue(0),)),
                i_cid: TermValue(0),
            }
        )
