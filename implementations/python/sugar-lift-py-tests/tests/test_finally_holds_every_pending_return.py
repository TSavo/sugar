"""A ``finally`` holds aside every ``return`` the arm reaching it took, and a
``finally`` that reads a parameter waits on the caller's actual (#7757,
leftovers of #8106).

A record holds every ``return`` it reached as one of its own entries
(``function_universe_sugar._is_return_entry``): a ``return`` inside an inner
``if`` arm is a ``GuardedReturn`` entry of the ``try`` body's record, and a
halt that left after it carries it on its record too. ``TrySugar`` sets
every such entry aside while the ``finally`` runs (``_pending_returns``): a
completed face's is pending, re-emitted after the ``finally``'s entries where
it falls through and discarded where the ``finally`` exits; a halt's record's
is dead on the halt's arm (the halt is guarded by the return's fall-through,
and the return leaves as its own completed face), so it is dropped
(``_halt_resumption``) -- before a ``finally``, an ``except`` handler and an
``except*`` handler alike. A handler's own ``return`` never stands beside
it, and a handler that falls through does not carry it into the tail.

A ``finally`` whose statements wait on the caller's actuals (a subscript of a
parameter) is a deferred native-operation carrier: it is composed beneath
the arm once the caller's actual discharges it (``after_discharge``), never
read as an ``ExitSet`` before then -- under a ``try`` and a ``try*`` alike
(``_try_outcome``).
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


_SUBSCRIPTING_STAR_FINALLY = (
    "def helper(i):\n"
    "    try:\n"
    "        x = 1\n"
    "    except* ValueError:\n"
    "        pass\n"
    "    finally:\n"
    "        y = (10, 20, 30)[i]\n"
    "    return y\n"
)


def test_a_try_star_finally_that_subscripts_a_parameter_defers_to_the_caller() -> None:
    # ``try*`` reads its outcome the one way a ``try`` does (``_try_outcome``):
    # a ``finally`` waiting on the caller's actual is never normalized as an
    # ``ExitSet`` before it discharges.
    function = _function(_SUBSCRIPTING_STAR_FINALLY)
    (coordinate,) = function.sugar().formal_coordinates

    pending = function.sugar().desugar(None)

    assert isinstance(pending, NativeOperationExitCarrierV1), type(pending)
    assert pending.demand.operator == "subscript"
    assert pending.demand.operand_coordinate_cids == (None, coordinate.coordinate_cid)


def test_a_deferred_try_star_finally_resolves_with_the_callers_actual() -> None:
    function = _function(_SUBSCRIPTING_STAR_FINALLY)
    (coordinate,) = function.sugar().formal_coordinates
    pending = function.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1), type(pending)

    for actual, expected in ((1, 20), (2, 30)):
        exits = pending.discharge(None, {coordinate.coordinate_cid: TermValue(actual)})
        assert isinstance(exits, ExitSet), type(exits)
        returns = [entry for record in _returns(exits) for entry in record]
        assert [entry.value for entry in returns] == [TermValue(expected)], returns


def _assert_one_return_per_record(exits: ExitSet, *expected: int) -> None:
    """Each completed record holds exactly one ``return``, and the records'
    returns are ``expected`` (in any order). A record that holds two (a dead
    guarded ``return`` beside a live one) fails here."""
    records = _returns(exits)
    for record in records:
        assert len(record) == 1, record
    values = [record[0].value for record in records]
    assert len(values) == len(expected), values
    for value in expected:
        assert TermValue(value) in values, values


def test_an_except_handlers_return_stands_alone_on_its_record() -> None:
    # The raise leaves after the guarded ``return 1``, on the path where
    # ``a < b`` fails: the halt's record holds that return, dead there. The
    # handler resumes without it, so its ``return 2`` is the record's only
    # return; ``return 1`` leaves as its own face under ``a < b``.
    exits = _discharged_on_symbolic_actuals(
        "def f(a, b):\n"
        "    try:\n"
        "        if a < b:\n"
        "            return 1\n"
        "        raise ValueError()\n"
        "    except ValueError:\n"
        "        return 2\n"
    )
    _assert_one_return_per_record(exits, 1, 2)


def test_an_except_handler_that_falls_through_leaves_the_dead_return_behind() -> None:
    # The handler falls through: the tail's ``return 3`` is the only return
    # on the handler's record, never after the dead guarded ``return 1``.
    exits = _discharged_on_symbolic_actuals(
        "def f(a, b):\n"
        "    try:\n"
        "        if a < b:\n"
        "            return 1\n"
        "        raise ValueError()\n"
        "    except ValueError:\n"
        "        pass\n"
        "    return 3\n"
    )
    _assert_one_return_per_record(exits, 1, 3)


def test_an_except_star_handler_that_falls_through_leaves_the_dead_return_behind() -> (
    None
):
    # ``except*`` resumes its handlers from the halt's record the same way.
    exits = _discharged_on_symbolic_actuals(
        "def f(a, b):\n"
        "    try:\n"
        "        if a < b:\n"
        "            return 1\n"
        "        raise ValueError()\n"
        "    except* ValueError:\n"
        "        pass\n"
        "    return 3\n"
    )
    _assert_one_return_per_record(exits, 1, 3)
