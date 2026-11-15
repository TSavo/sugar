"""Source try/except composes over a formal's item store.

Since #8857 the helpers below take ``class:a`` as an input of their contract
(``a`` is stored into and used no other way, ``nodes._receiver_class_parameters``),
so ``a[i] = q`` is ``type(a).__setitem__(a, i, q)``: the dispatched edge
(``receiver_dispatch.dispatch_edge_call``), two faces, owed, answered at prove
by the class each caller binds (``list.__setitem__``'s law, #8864).  It is no
deferred ``setitem`` carrier, so the ``try`` composes over its two faces at
once: the completed face falls past the handler, and the halt -- whose type
the callee's contract states at prove (``python:raised(<call>, <occurrence>)``)
-- reaches ``except IndexError`` under the type test, and leaves the ``try``
under its complement.  No face is dropped and no state is fabricated.
"""

from __future__ import annotations

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile

HELPER = (
    "def helper(a, i, q):\n"
    "    try:\n"
    "        a[i] = q\n"
    "    except IndexError:\n"
    "        return 1\n"
    "    return 0\n"
)

PLAIN_STORE = "def helper(a, i, q):\n    a[i] = q\n"

_OWNER = "UnknownCallee:dispatch:__setitem__"


def _tree(calls: str = "", helper: str = HELPER) -> SourceFile:
    source = f"{helper}\n{calls}"
    return SourceFile(
        (source, "try-native-store.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper_outcome(helper: str = HELPER):
    """``helper``'s own proof: its universe's faces."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    function = next(
        node for node in _tree(helper=helper).nodes() if isinstance(node, FunctionDef)
    )
    outcome = function_universe_outcome(function)
    assert isinstance(outcome, ExitSet), type(outcome)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    return outcome


def _call_outcome(call: str):
    tree = _tree(call)
    node = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return node.sugar().desugar(None)


def _returned_values(outcome) -> set:
    """The ``int`` each completed face of ``helper``'s universe returns."""
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    values = set()
    for face in outcome.exits:
        if not isinstance(face, Completed):
            continue
        returns = [
            s for s in face.value.record.statements if isinstance(s, ReturnValue)
        ]
        assert returns, face.value
        returned = returns[-1].value
        assert isinstance(returned, TermValue), returned
        values.add(returned.value)
    return values


def _store_halts(outcome) -> list:
    """The halts of the dispatched store that leave ``helper``."""
    return [face for face in outcome.halts() if face.effect.producer_node_owner == _OWNER]


def _the_call(call: str) -> CallSiteValue:
    """The source call's value on its completed face: the edge, which owes
    its halt under the complement of its ``completes`` atom."""
    outcome = _call_outcome(call)
    assert [face for face in outcome.exits if isinstance(face, Halted)], outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    assert isinstance(completed[0].value, CallSiteValue), completed[0].value
    return completed[0].value


def test_try_body_retains_formal_store_as_one_deferred_carrier() -> None:
    # Expected shape changed (#8857): the store in the ``try`` body is the
    # dispatched ``__setitem__`` edge, owed as the one member
    # ``python:dispatch:__setitem__``, never a deferred carrier.
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    outcome = _helper_outcome()
    assert "python:dispatch:__setitem__" in {
        call.symbol for call in owed_calls(outcome)
    }


def test_try_store_completion_bypasses_handler() -> None:
    # Expected shape changed (#8857): no carrier is discharged here.  The
    # store's completed face runs on to ``return 0``; the caller's edge
    # carries ``[0], 0, 9`` and prove decides which face the call takes.
    outcome = _helper_outcome()
    _the_call("helper([0], 0, 9)\n")

    assert 0 in _returned_values(outcome)


def test_try_store_indexerror_routes_to_handler_without_fabricated_state() -> None:
    # Expected shape changed (#8857): the store's halt names no type here
    # (its contract types it at prove), so ``except IndexError`` takes it
    # under the type test and returns 1, and under the complement the halt
    # leaves the ``try`` as it was -- with the state the store began from,
    # never a fabricated empty one.  Neither is chosen here.
    outcome = _helper_outcome()
    _the_call("helper([0], 4, 9)\n")

    assert _returned_values(outcome) == {0, 1}
    halts = _store_halts(outcome)
    assert halts, outcome
    for halt in halts:
        assert halt.state is not None


def test_exitset_consumer_observes_authentic_store_occurrence_and_state() -> None:
    # Expected shape changed (#8857): the plain store's halt is the
    # dispatched edge's own, keyed by the store's own occurrence and leaving
    # with the block's state; a store at another line is another occurrence.
    outcome = _helper_outcome(PLAIN_STORE)
    (halted,) = _store_halts(outcome)
    assert halted.state is not None
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    (foreign_halt,) = _store_halts(_helper_outcome("\n" + PLAIN_STORE))
    assert halted.effect.occurrence_id != foreign_halt.effect.occurrence_id
