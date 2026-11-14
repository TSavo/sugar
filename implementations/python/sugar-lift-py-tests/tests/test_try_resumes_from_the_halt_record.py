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

The same holds for a ``finally`` beneath a completed body and beneath a
``return``: it continues from the record that arrives at it, and the exit it
let through is re-emitted after it (a pending ``return`` follows the
``finally``'s entries, and is discarded when the ``finally`` returns itself).
A halt raised inside a called function reaches the caller in the caller's
record at the call (``call_site_value.at_the_call``): a name the callee binds
never shadows the caller's, and what the callee did to an object the caller
can see before it raised reaches the caller as it does on completion. The halt
names the call it left through, so the caller's ``try`` reads which statement
raised it.
"""

from __future__ import annotations

from frame_fresh import fresh
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


_ONE = fresh(ListValue, (TermValue(1),))


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
    assert _holds(records, fresh(ListValue, (TermValue(1), TermValue(2)))), records


def test_a_finally_after_a_completed_body_reads_its_store() -> None:
    # The body completed after ``x = 1``: the ``finally`` continues from that
    # record, not from the context the try began in (``x = 0``).
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    x = 0\n"
            "    try:\n"
            "        x = 1\n"
            "    finally:\n"
            "        return x\n"
        )
    )
    assert _returned_value(outcome) == TermValue(1)


def test_a_finally_after_a_return_reads_the_store_before_it() -> None:
    # The body stored ``x = 1`` and returned; the ``finally`` reads the store,
    # and its own ``return`` discards the pending ``return 5``.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    x = 0\n"
            "    try:\n"
            "        x = 1\n"
            "        return 5\n"
            "    finally:\n"
            "        return x\n"
        )
    )
    assert _returned_value(outcome) == TermValue(1)


def test_a_return_the_body_took_follows_a_finally_that_falls_through() -> None:
    # The ``finally`` runs after the body's append and before the pending
    # ``return 7`` leaves: the record holds both appends and the return.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    try:\n"
            "        acc.append(1)\n"
            "        return 7\n"
            "    finally:\n"
            "        acc.append(2)\n"
        )
    )
    assert _returned_value(outcome) == TermValue(7)
    records = _records(outcome)
    assert _holds(records, _ONE), records
    assert _holds(records, fresh(ListValue, (TermValue(1), TermValue(2)))), records


def test_a_handler_reads_the_callers_name_not_the_callees() -> None:
    # ``g`` binds its own local ``x = 2`` and raises: the halt reaches ``f``
    # at the call, in ``f``'s record there, so the handler returns ``f``'s 1.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    x = 1\n"
            "    try:\n"
            "        g()\n"
            "    except ValueError:\n"
            "        return x\n"
            "def g():\n"
            "    x = 2\n"
            "    raise ValueError()\n"
        )
    )
    assert _returned_value(outcome) == TermValue(1)


def test_a_handler_reads_what_the_callee_did_to_the_callers_list() -> None:
    # ``g`` appends to the caller's own list and raises: the append is not
    # rolled back, so the halt reaches ``f`` with ``acc`` as the completed
    # path would leave it (``[1]``), never the ``[]`` it held at the call.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    try:\n"
            "        g(acc)\n"
            "    except ValueError:\n"
            "        return acc\n"
            "def g(a):\n"
            "    a.append(1)\n"
            "    raise ValueError()\n"
        )
    )
    assert _returned_value(outcome) == _ONE


def test_a_callee_local_is_not_carried_beside_the_callers_list() -> None:
    # ``g`` binds a list of its own before it appends to the caller's: the
    # handler reads the caller's ``acc`` after the append, and ``g``'s ``acc``
    # stays in ``g``'s frame.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    try:\n"
            "        g(acc)\n"
            "    except ValueError:\n"
            "        return acc\n"
            "def g(a):\n"
            "    acc = [9]\n"
            "    a.append(1)\n"
            "    raise ValueError()\n"
        )
    )
    assert _returned_value(outcome) == _ONE


def test_a_handler_reads_the_state_of_the_call_that_raised() -> None:
    # Two body statements may halt with different ``x``: ``h()`` before
    # ``x = 2`` and ``g()`` after it.  The raise inside ``g`` leaves it
    # stamped with the call it left through (``call_site_value.call_owned``),
    # so the handler's ``try`` grounds its edge to ``g()`` and reads 2.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    x = 1\n"
            "    try:\n"
            "        h()\n"
            "        x = 2\n"
            "        g()\n"
            "    except ValueError:\n"
            "        return x\n"
            "def g():\n"
            "    raise ValueError()\n"
            "def h():\n"
            "    return 0\n"
        )
    )
    assert _returned_value(outcome) == TermValue(2)


def _read_after(source: str):
    """What ``f`` returns, or the refusal that names the read."""
    from sugar_source_tree.panic import SugarNotWritten

    try:
        return _returned_value(function_universe_outcome(_function(source)))
    except SugarNotWritten as refusal:
        return refusal


def test_a_global_the_callee_stored_before_its_raise_is_read_as_on_completion() -> (
    None
):
    # ``g`` stores the module global ``G`` and raises.  The handler's read of
    # ``G`` is what a read after ``g`` completing is -- the module binding a
    # nested scope writes is cited undecided where ``f`` reads it -- never
    # the ``0`` the module bound before the call.
    from sugar_source_tree.panic import SugarNotWritten

    halted = _read_after(
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    except ValueError:\n"
        "        return G\n"
        "G = 0\n"
        "def g():\n"
        "    global G\n"
        "    G = 1\n"
        "    raise ValueError()\n"
    )
    completed = _read_after(
        "def f():\n"
        "    g()\n"
        "    return G\n"
        "G = 0\n"
        "def g():\n"
        "    global G\n"
        "    G = 1\n"
    )
    assert halted != TermValue(0)
    assert isinstance(halted, SugarNotWritten) == isinstance(
        completed, SugarNotWritten
    ), (halted, completed)


def test_a_call_halt_keeps_what_the_caller_did_before_the_call() -> None:
    # The caller appended before the call; the callee binds a list of its own
    # under the same name.  The handler reads the caller's ``acc``.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    try:\n"
            "        acc.append(1)\n"
            "        g()\n"
            "    except ValueError:\n"
            "        return acc\n"
            "def g():\n"
            "    acc = [9]\n"
            "    raise ValueError()\n"
        )
    )
    assert _returned_value(outcome) == _ONE
    assert _holds(_records(outcome), _ONE), _records(outcome)
