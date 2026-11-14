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


def test_a_handler_reads_the_callers_list_wherever_the_call_sits() -> None:
    # The call is an assignment's value, not a statement alone: nothing the
    # statement evaluates before ``g(acc)`` can halt, so the halt leaving
    # ``g`` carries ``acc`` as ``g`` left it (``_halts_before``), ``[1]``.
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
    assert _returned_value(outcome) == _ONE


def test_a_callee_appending_to_a_module_list_is_seen_after_it_completes() -> None:
    # ``g`` appends to the module's list, which ``f`` reads too: the caller
    # holds the object the callee reaches (``_callee_reach``), so
    # ``f`` reads it as ``g`` left it, never the ``[]`` the module bound.
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
    assert _returned_value(outcome) == _ONE


def test_a_callee_appending_to_a_module_list_is_seen_after_it_raises() -> None:
    # The same append, then a raise: the halt leaving ``g`` carries the
    # module list as the completed arm does.
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
    assert _returned_value(outcome) == _ONE


def test_a_module_list_a_callee_may_change_unfollowed_is_not_its_old_value() -> None:
    # ``g``'s body loops, so it is not followed: the module list it reaches
    # takes the exposure every operand handed to such a call takes, an
    # unknown after the call, never the ``[]`` the module bound.
    returned = _read_after(
        "def f():\n"
        "    g()\n"
        "    return L\n"
        "L = []\n"
        "def g():\n"
        "    for _ in (1,):\n"
        "        L.append(1)\n"
    )
    assert returned != ListValue(())


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
    assert returned != ListValue(())


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
    assert returned != ListValue(())


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
    assert returned != ListValue(())


def test_a_nested_append_to_a_cell_is_seen_by_the_enclosing_function() -> None:
    # ``inner`` appends to the enclosing ``acc`` it reads as a closure cell:
    # the call is followed as a source helper, the cell as the caller's
    # object (``_callee_reach``), so ``f`` reads ``[1]``.
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
    assert _returned_value(outcome) == _ONE


def test_a_nested_append_to_a_cell_then_a_raise_is_seen_at_the_handler() -> None:
    # The same append, then a raise: the halt leaving ``inner`` carries the
    # cell as the completed arm does.
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
    assert _returned_value(outcome) == _ONE


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
    assert returned != ListValue(())


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
    # binds the cell's value at the call (``Call._closure_cells``), the body
    # writes it, and the enclosing function reads the write after the call
    # (``source_helper_actual_states``): ``n + 1``, never the ``4`` bound
    # before and never a refusal.
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
    assert _returned_value(outcome) == TermValue(5)


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
    assert returned != ListValue(())


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
    assert _read_after(source) != ListValue(())


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
    assert returned != ListValue(())


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
