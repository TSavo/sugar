"""A ``finally`` holds aside every ``return`` the arm reaching it took, and a
``finally`` that reads a parameter waits on the caller's actual (#7757,
leftovers of #8106).

A record holds every ``return`` it reached as one of its own entries
(``function_universe_sugar._is_return_entry``): a ``return`` inside an inner
``if`` arm is a ``GuardedReturn`` entry of the ``try`` body's record, and a
halt that left after it carries it on its record too. ``TrySugar`` holds
every such entry aside while the ``finally`` runs (``_pending_returns``), on
a completed face and on a halt alike: re-emitted after the ``finally``'s
entries where it falls through, discarded where the ``finally`` exits.

A ``finally`` whose statements wait on the caller's actuals (a subscript of a
parameter) is a deferred native-operation carrier: it is composed beneath
the arm once the caller's actual discharges it (``after_discharge``), never
read as an ``ExitSet`` before then.
"""

from __future__ import annotations

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    GuardedReturn,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "finally_pending_returns.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _discharged_on_symbolic_actuals(source: str) -> ExitSet:
    """``f(a, b)``'s exits once symbolic actuals discharge its ``a < b``."""
    pending = _function(source).sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1), type(pending)
    left, right = pending.coordinates
    exits = pending.discharge(
        None,
        {
            left.coordinate_cid: SymbolicValue(make_var("actual_a")),
            right.coordinate_cid: SymbolicValue(make_var("actual_b")),
        },
    )
    assert isinstance(exits, ExitSet), type(exits)
    return exits


def _returns(exits: ExitSet) -> list[tuple]:
    """The ``return`` entries of every completed exit's record, in order."""
    return [
        tuple(
            entry
            for entry in exit_.value.record.statements
            if isinstance(entry, (ReturnValue, GuardedReturn))
        )
        for exit_ in exits.exits
        if isinstance(exit_, Completed)
    ]


def test_a_return_in_finally_discards_a_return_taken_in_an_inner_arm() -> None:
    # Python: ``try: if c: return 1 finally: return 2`` returns 2 on every
    # path; the pending ``return 1`` never stands beside it.
    exits = _discharged_on_symbolic_actuals(
        "def f(a, b):\n"
        "    try:\n"
        "        if a < b:\n"
        "            return 1\n"
        "    finally:\n"
        "        return 2\n"
    )
    assert exits.exits, exits
    assert all(isinstance(exit_, Completed) for exit_ in exits.exits), exits
    returns = _returns(exits)
    assert returns, exits
    for record in returns:
        assert record == (ReturnValue(TermValue(2)),), record


def test_a_return_in_finally_discards_a_return_the_halt_record_holds() -> None:
    # The raise leaves after the guarded ``return 1``: its record holds that
    # return. The ``finally`` runs without it, and its own ``return 2``
    # supersedes the raise alone: no record holds the return of 1.
    exits = _discharged_on_symbolic_actuals(
        "def f(a, b):\n"
        "    try:\n"
        "        if a < b:\n"
        "            return 1\n"
        "        raise ValueError()\n"
        "    finally:\n"
        "        return 2\n"
    )
    assert exits.exits, exits
    assert all(isinstance(exit_, Completed) for exit_ in exits.exits), exits
    returns = _returns(exits)
    assert returns, exits
    for record in returns:
        assert record == (ReturnValue(TermValue(2)),), record


def test_a_return_in_an_inner_arm_follows_a_finally_that_falls_through() -> None:
    # Under ``a < b`` the function returns 1 after the ``finally`` bound
    # ``x = 3``; on the other path the tail reads the ``finally``'s ``x``.
    exits = _discharged_on_symbolic_actuals(
        "def f(a, b):\n"
        "    x = 0\n"
        "    try:\n"
        "        if a < b:\n"
        "            return 1\n"
        "    finally:\n"
        "        x = 3\n"
        "    return x\n"
    )
    returns = [entry for record in _returns(exits) for entry in record]
    assert [entry.value for entry in returns] == [TermValue(1), TermValue(3)], (
        returns
    )
    assert all(isinstance(entry, GuardedReturn) for entry in returns), returns


_SUBSCRIPTING_FINALLY = (
    "def helper(i):\n"
    "    try:\n"
    "        x = 1\n"
    "    finally:\n"
    "        y = (10, 20, 30)[i]\n"
    "    return y\n"
)


def test_a_finally_that_subscripts_a_parameter_defers_to_the_caller() -> None:
    function = _function(_SUBSCRIPTING_FINALLY)
    (coordinate,) = function.sugar().formal_coordinates

    pending = function.sugar().desugar(None)

    assert isinstance(pending, NativeOperationExitCarrierV1), type(pending)
    assert pending.demand.operator == "subscript"
    assert pending.demand.operand_coordinate_cids == (None, coordinate.coordinate_cid)


def test_a_deferred_finally_resolves_with_the_callers_actual() -> None:
    function = _function(_SUBSCRIPTING_FINALLY)
    (coordinate,) = function.sugar().formal_coordinates
    pending = function.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1), type(pending)

    for actual, expected in ((1, 20), (2, 30)):
        exits = pending.discharge(None, {coordinate.coordinate_cid: TermValue(actual)})
        assert isinstance(exits, ExitSet), type(exits)
        returns = [entry for record in _returns(exits) for entry in record]
        assert [entry.value for entry in returns] == [TermValue(expected)], returns
