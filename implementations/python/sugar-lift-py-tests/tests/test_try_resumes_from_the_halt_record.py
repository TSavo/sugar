"""An ``except`` handler and a ``finally`` run from the state the raise carries
(#7757, found by #8089).

A halt's record is everything the block reached before it halted: every
store, rebind, container mutation and walrus bind, in its entries and in the
context it halted in. Python never rolls any of it back, so the suite that
catches the halt continues after that record, exactly as a block continues
after a statement (``reduce_block_to_exitset(..., after=)``,
``function_universe_sugar.resumed``). The handler used to reduce from the
context the ``try`` began in, beside an empty record: whatever the body did
before the raise was invisible to it, and the record the try left with by the
handler held none of it.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "try_halt_record.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _records(outcome) -> list:
    """The record of every completed exit of ``outcome``."""
    return [
        tuple(getattr(getattr(exit_.value, "record", exit_.value), "statements", ()))
        for exit_ in outcome.exits
        if isinstance(exit_, Completed)
    ]


def _holds(records, value) -> bool:
    """Whether some record (or a block nested in one) holds ``value``."""
    from sugar_lift_py_tests.floor.block_value import BlockValue

    pending = [entry for record in records for entry in record]
    while pending:
        entry = pending.pop()
        if entry == value:
            return True
        if isinstance(entry, BlockValue):
            pending.extend(entry.statements)
    return False


def _returned_value(outcome):
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.universe_value import UniverseValue

    universe = outcome.completed_value()
    assert isinstance(universe, UniverseValue), outcome
    (returned,) = [
        entry
        for entry in universe.record.statements
        if isinstance(entry, ReturnValue)
    ]
    return returned.value


_ONE = ListValue((TermValue(1),))


def test_a_handler_reads_an_append_made_before_the_raise() -> None:
    # ``acc.append(1)`` ran before the raise: the handler returns ``[1]``,
    # and the try leaves through the handler with the append on its record.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    try:\n"
            "        acc.append(1)\n"
            "        raise ValueError()\n"
            "    except ValueError:\n"
            "        return acc\n"
        )
    )
    assert _returned_value(outcome) == _ONE
    assert _holds(_records(outcome), _ONE), _records(outcome)


def test_a_handler_reads_a_rebind_made_before_the_raise() -> None:
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    x = 0\n"
            "    try:\n"
            "        x = 1\n"
            "        raise ValueError()\n"
            "    except ValueError:\n"
            "        return x\n"
        )
    )
    assert _returned_value(outcome) == TermValue(1)


def test_a_finally_reads_an_append_made_before_the_raise() -> None:
    # The raise reaches the ``finally`` after the append; its ``return``
    # supersedes the raise with ``[1]``.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    try:\n"
            "        acc.append(1)\n"
            "        raise ValueError()\n"
            "    finally:\n"
            "        return acc\n"
        )
    )
    assert _returned_value(outcome) == _ONE
    assert _holds(_records(outcome), _ONE), _records(outcome)


def test_a_finally_reads_a_store_made_before_the_raise() -> None:
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    x = 0\n"
            "    try:\n"
            "        x = 1\n"
            "        raise ValueError()\n"
            "    finally:\n"
            "        return x\n"
        )
    )
    assert _returned_value(outcome) == TermValue(1)


def test_an_outer_handler_reads_what_a_nested_try_stored_before_the_raise() -> None:
    # The inner handler does not match: the raise leaves the inner try with
    # its record (``x = 2``), the outer body's prefix (``x = 1``) before it,
    # and the outer handler reads ``x`` there.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    x = 0\n"
            "    try:\n"
            "        x = 1\n"
            "        try:\n"
            "            x = 2\n"
            "            raise ValueError()\n"
            "        except KeyError:\n"
            "            return 3\n"
            "    except ValueError:\n"
            "        return x\n"
        )
    )
    assert _returned_value(outcome) == TermValue(2)


def test_a_handler_after_a_loop_that_raised_carries_what_the_items_did() -> None:
    # Item 0 appended 1 and went on; item 1 appended 2 and raised.  The raise
    # leaves the loop with both items' appends (#8089), and the handler that
    # catches it continues after that record: the try leaves with both.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    try:\n"
            "        for x in g():\n"
            "            acc.append(x)\n"
            "            if x == 2:\n"
            "                raise ValueError()\n"
            "    except ValueError:\n"
            "        return acc\n"
            "    return None\n"
            "def g():\n"
            "    return (1, 2)\n"
        )
    )
    records = _records(outcome)
    assert records, outcome
    assert _holds(records, _ONE), records
    assert _holds(records, ListValue((TermValue(1), TermValue(2)))), records
