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

A call of a same-file function is its coordinate and edge, joined at prove
(#7757 steps 5 and 6, the owner's ruling "Edge, join at prove", #8705; the
application of a callee body at lift and the projection of its halt and
effects into the caller are deleted, #8739, #8751).  The call completes under
its ``completes`` atom and halts under the complement, so a ``try`` around it
has a completed face for each: the body's and the handler's.  The halt
reaches the handler in the caller's record at the call: a name the callee
binds never shadows the caller's.  What the callee did to an object it can
reach (an actual, a cell, a module global) is the one exposure rule's read
after the call: on the call's completed face the formal the binder bound it
to, ``python:after(<call result>, <formal>)``, keyed on the call (#7757 step
7); on its halted face, and where the call alone does not decide it, the
unknown (``python:receiver_after_call``), or the ``global:`` input.  Its
value is the post-call object state, joined at prove from the callee's
contract, so these tests expect that read.
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
    """What the function's one completed face returns.  A call the body does
    not follow (an import's, a builtin handed a callable) has two faces: it
    completes under its completes atom and halts under the complement, so the
    universe is the completed face beside that halt."""
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.universe_value import UniverseValue

    completed = [exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)]
    assert len(completed) == 1, outcome
    universe = completed[0].value
    assert isinstance(universe, UniverseValue), outcome
    (returned,) = [
        entry
        for entry in universe.record.statements
        if isinstance(entry, ReturnValue)
    ]
    return returned.value


def _returns(outcome) -> list:
    """What every completed face of ``outcome`` returns: a ``try`` around a
    same-file call has the body's face and the handler's (the call's two
    faces, #8705)."""
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    found = []
    for exit_ in outcome.exits:
        if not isinstance(exit_, Completed):
            continue
        record = getattr(exit_.value, "record", None)
        found.extend(
            entry.value
            for entry in getattr(record, "statements", ()) or ()
            if isinstance(entry, ReturnValue)
        )
    return found


def _term_name(value):
    term = getattr(value, "term", None)
    return getattr(term, "name", None)


def _after_call(value) -> bool:
    """The one exposure rule's read of an object after a call that may
    change it: the formal the call's binder bound it to on the call's
    completed face (``python:after``, keyed on the call), else the unknown
    (``python:receiver_after_call``); its value is the post-call object
    state, joined at prove (#7757 step 7)."""
    return _term_name(value) in ("python:after", "python:receiver_after_call")


def _global_input(value, name: str) -> bool:
    """The module global read as the contract's free input (#8704)."""
    return _term_name(value) == f"global:{name}"


_ONE = fresh(ListValue, (TermValue(1),))
# The ``[]`` a module or frame bound; a list compares by its elements alone.
_EMPTY = fresh(ListValue, ())


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


# The inner ``try`` never completes: its body always raises and its one arm
# returns.  What its halt carries out of it is the state at the raise
# (``_HaltEdgeJoin.escaping_state``, ``_Splice.halted``), never the state its
# completion would have left -- which binds nothing, so the outer handler
# used to read the key of ``x = 1``.
_NESTED_TRY_STORES_THEN_RAISES = (
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


def test_the_truthful_half_reads_the_store_the_raising_path_bound() -> None:
    # TRUTHFUL: Python returns 2, the value ``x = 2`` bound before the raise.
    outcome = function_universe_outcome(_function(_NESTED_TRY_STORES_THEN_RAISES))
    assert _returned_value(outcome) == TermValue(2)


def test_the_lying_half_reads_the_store_before_the_nested_try() -> None:
    # LYING: 1, the binding standing before the nested try, read as if the
    # nested try's halt carried what its (never reached) completion left.
    outcome = function_universe_outcome(_function(_NESTED_TRY_STORES_THEN_RAISES))
    assert _returned_value(outcome) != TermValue(1)


def test_an_outer_handler_reads_a_nested_try_store_through_an_if() -> None:
    # The same nested try beneath an ``if``: the ``if`` passes on what the
    # halt leaving the nested try carries (``_compound_halt_state``), so the
    # outer handler still reads 2.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    x = 0\n"
            "    try:\n"
            "        x = 1\n"
            "        if True:\n"
            "            try:\n"
            "                x = 2\n"
            "                raise ValueError()\n"
            "            except KeyError:\n"
            "                return 3\n"
            "    except ValueError:\n"
            "        return x\n"
        )
    )
    assert _returned_value(outcome) == TermValue(2)


def test_a_handler_after_a_loop_that_raised_carries_what_the_items_did() -> None:
    # Item 0 appended 1 and went on; item 1 appended 2 and raised.  The raise
    # leaves the loop with both items' appends (#8089), and the handler that
    # catches it continues after that record: the try leaves with both.
    # The iterable is the display itself: it used to be ``g()`` with
    # ``def g(): return (1, 2)``, whose body the call applied.  A same-file
    # call is its coordinate and edge (#8705), so a loop over its result is
    # the one undecided iteration (#8775) and its items are decided at prove.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    try:\n"
            "        for x in (1, 2):\n"
            "            acc.append(x)\n"
            "            if x == 2:\n"
            "                raise ValueError()\n"
            "    except ValueError:\n"
            "        return acc\n"
            "    return None\n"
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
    # (The body's own completed face, the call's other face, returns
    # nothing; whether ``g`` raises is decided at prove.)
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
    returns = _returns(outcome)
    assert TermValue(1) in returns, outcome
    assert TermValue(2) not in returns


def _handler_reads_after_call(outcome) -> None:
    """The handler's read of an object the raising callee could reach: the
    exposure rule's read after the call, never the value before it and
    never a value read off the callee's body.  What the callee did to it
    before it raised is the post-call object state, joined at prove (step
    7, not merged); it used to be ``[1]``, the body's append followed at the
    call."""
    returns = _returns(outcome)
    assert any(_after_call(value) for value in returns), returns
    assert _EMPTY not in returns
    assert _ONE not in returns


def test_a_handler_reads_what_the_callee_did_to_the_callers_list() -> None:
    # ``g`` appends to the caller's own list and raises: the append is not
    # rolled back, so the handler never reads the ``[]`` it held at the call.
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
    _handler_reads_after_call(outcome)


def test_a_handler_reads_the_callers_list_wherever_the_call_sits() -> None:
    # The call is an assignment's value, not a statement alone: the handler
    # reads ``acc`` after the call wherever the call sits.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    try:\n"
            "        y = g(acc)\n"
            "    except ValueError:\n"
            "        return acc\n"
            "def g(a):\n"
            "    a.append(1)\n"
            "    raise ValueError()\n"
        )
    )
    _handler_reads_after_call(outcome)


def test_a_callee_appending_to_a_module_list_is_seen_after_it_completes() -> None:
    # ``g`` appends to the module's list, which ``f`` reads too.  ``f``'s
    # contract reads ``L`` as its free input ``global:L`` (#8704): the
    # object, never the ``[]`` the module bound.  Its contents after ``g``
    # are the post-call object state, joined at prove (step 7, not merged);
    # this used to be ``[1]``, ``g``'s append followed at the call.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    g()\n"
            "    return L\n"
            "L = []\n"
            "def g():\n"
            "    L.append(1)\n"
        )
    )
    returned = _returned_value(outcome)
    assert _global_input(returned, "L"), returned
    assert returned != _EMPTY and returned != _ONE


def test_a_callee_appending_to_a_module_list_is_seen_after_it_raises() -> None:
    # The same append, then a raise: the handler reads the module list as
    # the completed path does, the input ``global:L`` (step 7 decides its
    # contents at prove).
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    try:\n"
            "        g()\n"
            "    except ValueError:\n"
            "        return L\n"
            "L = []\n"
            "def g():\n"
            "    L.append(1)\n"
            "    raise ValueError()\n"
        )
    )
    returns = _returns(outcome)
    assert any(_global_input(value, "L") for value in returns), returns
    assert _EMPTY not in returns and _ONE not in returns


def _reads_after_call(outcome) -> None:
    """``f`` reads ``acc`` after ``g(acc, ...)``: the exposure rule's read
    after the call.  Which list ``g`` leaves (by its branch, its early
    return) is the post-call object state, joined at prove from ``g``'s
    contract under the call's actuals (step 7, not merged).  These used to
    read ``[1]`` or ``[]`` off ``g``'s body followed at the call."""
    returned = _returned_value(outcome)
    assert _after_call(returned), returned
    assert returned != _EMPTY and returned != _ONE


def test_a_callee_appending_under_an_if_is_seen_where_the_branch_ran() -> None:
    # ``g`` appends only under ``if c``; ``f`` passed ``True`` (Python:
    # ``[1]``, decided at prove).
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    g(acc, True)\n"
            "    return acc\n"
            "def g(a, c):\n"
            "    if c:\n"
            "        a.append(1)\n"
        )
    )
    _reads_after_call(outcome)


def test_a_callee_appending_under_an_if_is_not_seen_where_it_did_not_run() -> None:
    # The same callee handed ``False`` (Python: ``[]``, decided at prove).
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    g(acc, False)\n"
            "    return acc\n"
            "def g(a, c):\n"
            "    if c:\n"
            "        a.append(1)\n"
        )
    )
    _reads_after_call(outcome)


def test_an_early_return_before_the_append_leaves_the_list_as_it_was() -> None:
    # ``g`` returns before its append when ``c`` holds (Python: ``[]``,
    # decided at prove).
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    g(acc, True)\n"
            "    return acc\n"
            "def g(a, c):\n"
            "    if c:\n"
            "        return\n"
            "    a.append(1)\n"
        )
    )
    _reads_after_call(outcome)


def test_an_early_return_not_taken_leaves_the_append() -> None:
    # The same callee handed ``False`` (Python: ``[1]``, decided at prove).
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    g(acc, False)\n"
            "    return acc\n"
            "def g(a, c):\n"
            "    if c:\n"
            "        return\n"
            "    a.append(1)\n"
        )
    )
    _reads_after_call(outcome)


def test_a_module_list_a_callee_may_change_unfollowed_is_not_its_old_value() -> None:
    # ``g`` appends inside a loop, which leaves the list unknown in its
    # frame: the module list takes the exposure every operand handed to a
    # call takes, an unknown after the call, never the ``[]`` the module
    # bound.
    returned = _read_after(
        "def f():\n"
        "    g()\n"
        "    return L\n"
        "L = []\n"
        "def g():\n"
        "    for _ in (1,):\n"
        "        L.append(1)\n"
    )
    assert returned != _EMPTY


def test_a_method_call_then_a_read_of_a_module_list_is_not_stale() -> None:
    # ``O.m()`` runs a source method the caller does not follow, which
    # appends to the module's list: a method on a receiver whose value runs
    # code reaches every module object the caller reads
    # (``_ambient_targets``), so ``L`` is never the ``[]`` the module bound.
    returned = _read_after(
        "def f():\n"
        "    O.m()\n"
        "    return L\n"
        "L = []\n"
        "class C:\n"
        "    def m(self):\n"
        "        L.append(1)\n"
        "O = C()\n"
    )
    assert returned != _EMPTY


def test_an_imported_call_then_a_read_of_a_module_list_is_not_stale() -> None:
    # An imported callee is never followed: it may reach the module's list
    # (through an import of this module, a callback, ...), so ``L`` after it
    # is never the ``[]`` the module bound.
    returned = _read_after(
        "import os\n"
        "def f():\n"
        "    os.getcwd()\n"
        "    return L\n"
        "L = []\n"
    )
    assert returned != _EMPTY


def test_a_lambda_call_then_a_read_of_a_module_list_is_not_stale() -> None:
    # A callable value (a lambda bound to a name) is called: its value runs
    # code, so every module object the caller reads is exposed to it.
    returned = _read_after(
        "def f():\n"
        "    h = lambda: L.append(1)\n"
        "    h()\n"
        "    return L\n"
        "L = []\n"
    )
    assert returned != _EMPTY


def test_a_nested_append_to_a_cell_is_seen_by_the_enclosing_function() -> None:
    # ``inner`` appends to the enclosing ``acc`` it reads as a closure cell:
    # the call carries the cell (``py.closure``) on its edge, and ``f``
    # reads ``acc`` after the call, never the ``[]`` it bound.  The list
    # ``inner`` leaves is the post-call state of the cell (step 7, not
    # merged); this used to be ``[1]``, ``inner``'s body followed.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    def inner():\n"
            "        acc.append(1)\n"
            "    inner()\n"
            "    return acc\n"
        )
    )
    returned = _returned_value(outcome)
    assert _after_call(returned), returned
    assert returned != _EMPTY and returned != _ONE


def test_a_nested_append_to_a_cell_then_a_raise_is_seen_at_the_handler() -> None:
    # The same append, then a raise: the handler reads the cell after the
    # call, as the completed path does (step 7 decides its contents).
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    def inner():\n"
            "        acc.append(1)\n"
            "        raise ValueError()\n"
            "    try:\n"
            "        inner()\n"
            "    except ValueError:\n"
            "        return acc\n"
        )
    )
    _handler_reads_after_call(outcome)


def test_a_nested_nonlocal_append_is_never_the_old_list() -> None:
    # ``inner`` declares ``acc`` ``nonlocal`` and appends to it: the
    # enclosing function's read after the call is the list as ``inner`` left
    # it (or refused by name), never the ``[]`` it bound.
    returned = _read_after(
        "def f():\n"
        "    acc = []\n"
        "    def inner():\n"
        "        nonlocal acc\n"
        "        acc.append(1)\n"
        "    inner()\n"
        "    return acc\n"
    )
    assert returned != _EMPTY


def test_a_nested_nonlocal_rebind_is_never_the_old_value() -> None:
    # ``bump`` rebinds the enclosing ``n``: its write is the caller's
    # binding, so the read after the call is never the ``0`` bound before.
    returned = _read_after(
        "def f():\n"
        "    n = 0\n"
        "    def bump():\n"
        "        nonlocal n\n"
        "        n += 1\n"
        "    bump()\n"
        "    return n\n"
    )
    assert returned != TermValue(0)


def test_a_nested_nonlocal_increment_is_read_by_the_enclosing_function() -> None:
    # ``bump`` reads and writes the enclosing ``n`` through its cell: the call
    # carries the cell's value at the call (``py.closure``), and the
    # enclosing function reads ``n`` after the call, never the ``4`` bound
    # before and never a refusal.  The value ``bump`` writes (5) is the
    # post-call state of the cell, joined at prove (step 7, not merged);
    # this used to be read off ``bump``'s body at the call.
    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    n = 4\n"
            "    def bump():\n"
            "        nonlocal n\n"
            "        n += 1\n"
            "    bump()\n"
            "    return n\n"
        )
    )
    returned = _returned_value(outcome)
    assert _after_call(returned), returned
    assert returned not in (TermValue(4), TermValue(5))


def test_an_operator_on_a_source_object_then_a_module_list_is_not_stale() -> None:
    # ``O + 1`` runs ``C.__add__``, which appends to the module's list: an
    # operator whose operand's value is a source object may run code, so it
    # reaches every module object the caller reads (``_ambient_targets``),
    # as a call does.  ``L`` is never the ``[]`` the module bound.
    returned = _read_after(
        "def f():\n"
        "    O + 1\n"
        "    return L\n"
        "L = []\n"
        "class C:\n"
        "    def __add__(self, other):\n"
        "        L.append(other)\n"
        "        return self\n"
        "O = C()\n"
    )
    assert returned != _EMPTY


def _substituted_return_read(source: str):
    """The node the object the first function's last ``return`` reads is,
    after its body's substitution (the temporal rewrite)."""
    from sugar_source_tree.container_mutation import _identity
    from sugar_source_tree.nodes import Return

    substituted = _function(source).substitute({})
    returned = next(
        statement
        for statement in reversed(substituted.body)
        if isinstance(statement, Return)
    )
    return _identity(returned.value)


def test_a_generator_holding_a_module_list_reads_it_unknown_after_a_yield() -> None:
    # At ``yield 1`` the consumer runs code of its own before the frame
    # resumes (``L.append(...)``, say): the module list the generator frame
    # holds is exposed at the yield as a caller's is at an unfollowed call
    # (``_ambient_targets``), so the read after it is the list's value after
    # the yield, never the ``[]`` the module bound.
    read = _substituted_return_read(
        "L = []\n"
        "def g():\n"
        "    yield 1\n"
        "    return L\n"
    )
    assert read.kind == "ReceiverAfterCall"


def test_a_list_a_generator_yielded_is_read_unknown_after_the_yield() -> None:
    # The yielded list is handed to the consumer as an operand is to a call
    # (``_call_targets``): the frame's read of it after the resume is its
    # value after the yield, never the ``[1]`` it yielded.
    read = _substituted_return_read(
        "def g():\n"
        "    xs = [1]\n"
        "    yield xs\n"
        "    return xs\n"
    )
    assert read.kind == "ReceiverAfterCall"


def test_exec_of_a_constant_string_runs_code_then_a_module_list_is_not_stale() -> (
    None
):
    # ``exec`` runs the source it is handed, a constant string as much as any:
    # the law cites no builtin outside ``_cited().pure`` as running only its
    # operands' dunders, so no operand decides it (``_code_subjects`` is
    # None, never ``[]``) and it reaches every module object the caller
    # reads.  ``L`` is never the ``[]`` the module bound.
    from sugar_source_tree.container_mutation import _code_subjects
    from sugar_source_tree.nodes import Call

    source = "def f():\n    exec('L.append(1)')\n    return L\nL = []\n"
    (call,) = [node for node in _function(source).walk() if isinstance(node, Call)]
    assert _code_subjects(call, {}) is None
    assert _read_after(source) != _EMPTY


def test_a_builtin_exception_class_by_its_binding_runs_no_code() -> None:
    # ``ValueError()`` bound to the builtin class stores its actuals as
    # ``args`` (``BaseException_new``) and runs no code: it reaches nothing
    # beyond its operands (``_code_subjects`` is ``[]``).  A module class
    # spelled ``ValueError`` is source code: no read decides it (None).
    from sugar_source_tree.container_mutation import _code_subjects
    from sugar_source_tree.nodes import Call

    for source, expected in (
        ("def f():\n    raise ValueError()\n", []),
        (
            "def f():\n"
            "    raise ValueError()\n"
            "L = []\n"
            "class ValueError(Exception):\n"
            "    def __init__(self):\n"
            "        L.append(1)\n",
            None,
        ),
    ):
        (call,) = [node for node in _function(source).walk() if isinstance(node, Call)]
        assert _code_subjects(call, {}) == expected, source


def test_exec_in_a_function_reaches_the_object_a_local_list_is() -> None:
    # ``exec`` handed no globals mapping runs in the frame's namespaces: its
    # code reads ``xs`` from the frame's ``locals()`` snapshot, the very list
    # the local is bound to, and appends to it.  The read after it is the
    # list's value after the call (``_frame_targets``), never the ``[]`` the
    # local was bound to.
    read = _substituted_return_read(
        "def f():\n"
        "    xs = []\n"
        "    exec('xs.append(1)')\n"
        "    return xs\n"
    )
    assert read.kind == "ReceiverAfterCall"


def test_exec_in_a_function_never_rebinds_a_local_int() -> None:
    # CPython 3.13 (PEP 667): in a function ``exec`` writes the frame's
    # ``locals()`` snapshot, never its fast locals, so ``exec('x = 2')``
    # leaves ``x`` bound to ``1``; an ``int`` is no object a call changes.
    read = _substituted_return_read(
        "def f():\n"
        "    x = 1\n"
        "    exec('x = 2')\n"
        "    return x\n"
    )
    assert read.kind == "Constant"
    assert read.value == 1


def test_a_locals_mapping_handed_to_a_call_reaches_the_local_list() -> None:
    # ``g`` is handed the frame's ``locals()`` snapshot, which holds the list
    # ``xs`` is bound to: whatever ``g`` does through it reaches that list,
    # so the read after the call is its value after it, never ``[]``.
    read = _substituted_return_read(
        "def f():\n"
        "    xs = []\n"
        "    g(locals())\n"
        "    return xs\n"
        "def g(d):\n"
        "    for _ in (1,):\n"
        "        d['xs'].append(1)\n"
    )
    assert read.kind == "ReceiverAfterCall"


def test_exec_at_module_scope_rebinds_a_module_name() -> None:
    # At module scope ``locals()`` is the module's namespace itself, so
    # ``exec('x = 2')`` rebinds ``x``: the module threading's binding of
    # ``x`` after it is unknown (``_frame_targets``), never the ``1`` bound
    # before.
    from sugar_source_tree.container_mutation import _state

    unit = _function(
        "x = 1\n"
        "exec('x = 2')\n"
        "def f():\n"
        "    return x\n"
    ).unit
    after = _state(unit.module_binding_states().final["x"])
    assert after.kind == "ReceiverAfterCall"


def test_a_callable_handed_out_reaches_the_cell() -> None:
    # ``inner`` is handed to code the caller does not follow (a builtin that
    # calls it): the cell it appends to is exposed to that call, never read
    # as the ``[]`` bound before.
    returned = _read_after(
        "def f():\n"
        "    acc = []\n"
        "    def inner(_x):\n"
        "        acc.append(1)\n"
        "    list(map(inner, (1,)))\n"
        "    return acc\n"
    )
    assert returned != _EMPTY


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
    _handler_reads_after_call(outcome)
    assert fresh(ListValue, (TermValue(9),)) not in _returns(outcome)


def test_a_handler_reads_the_state_of_the_call_that_raised() -> None:
    # Two body statements may halt with different ``x``: ``h()`` before
    # ``x = 2`` and ``g()`` after it.  Each call halts under the complement
    # of its own ``completes`` atom, and the handler's ``try`` grounds the
    # halt of ``g()`` to its edge, where ``x`` is 2.  (The face where ``h()``
    # halts reads 1; ``h``'s contract states no halt, so prove refutes that
    # face, step 7, #8749.)
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
    assert TermValue(2) in _returns(outcome), outcome


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
    # nested scope writes is undecided, so ``f`` reads it through its
    # undecided key: its free ``global:G`` input, for which its row states
    # no value (#8704) -- never the ``0`` the module bound before the call.
    halted = _returns(
        function_universe_outcome(
            _function(
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
        )
    )
    completed = _returns(
        function_universe_outcome(
            _function(
                "def f():\n"
                "    g()\n"
                "    return G\n"
                "G = 0\n"
                "def g():\n"
                "    global G\n"
                "    G = 1\n"
            )
        )
    )
    assert halted and completed, (halted, completed)
    assert TermValue(0) not in halted, halted
    assert TermValue(0) not in completed, completed
    assert "global:G" in repr(halted), halted
    assert "global:G" in repr(completed), completed


def test_a_call_halt_keeps_what_the_caller_did_before_the_call() -> None:
    # The caller appended before the call; the callee binds a list of its own
    # under the same name.  The handler reads the caller's ``acc``: ``g()`` is
    # handed nothing and reaches no cell, so ``acc`` is not exposed to it.
    # (The body's own completed face, the call's other face, returns
    # nothing.)
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
    returns = _returns(outcome)
    assert _ONE in returns, outcome
    assert fresh(ListValue, (TermValue(9),)) not in returns
    assert _holds(_records(outcome), _ONE), _records(outcome)
