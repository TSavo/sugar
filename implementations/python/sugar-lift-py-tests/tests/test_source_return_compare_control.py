"""Same-file call results in a Compare that steers control.

A call of a same-file function is its coordinate and edge, joined at prove
(#7757 steps 5 and 6, the owner's ruling "Edge, join at prove", #8705; the
application of a callee body at lift is deleted, #8751).  ``lower() <
value`` therefore compares a call's result whose value the lift does not
have: which branch runs, and whether ``absent() < value`` raises
``TypeError``, is decided at prove, where each callee's contract joins its
edge.  What the lift states is each call's edge, with its own actuals, and
each callee's row with its own return.

This suite used to read the branch a call took, and the ``TypeError`` of
``None < 2``, off the callees' bodies followed at the call (``codex-3``).
"""

from __future__ import annotations

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ReturnValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile

SOURCE = (
    "def lower():\n"
    "    return 1\n"
    "def upper():\n"
    "    return 3\n"
    "def absent():\n"
    "    return None\n"
    "def choose(value):\n"
    "    if lower() < value:\n"
    "        return upper()\n"
    "    return lower()\n"
    "def exceptional(value):\n"
    "    if absent() < value:\n"
    "        return upper()\n"
    "    return lower()\n"
    "def identity_control(value):\n"
    "    if absent() is value:\n"
    "        return upper()\n"
    "    return lower()\n"
)


def _tree(calls: str = ""):
    context = TreeConstructionContextV1.for_source_call_construction()
    source = f"{SOURCE}\n{calls}"
    tree = SourceFile(
        (source, "source-return-compare-control.py", blake3_512_of(source.encode())),
        construction_context=context,
    )
    functions = {
        node.name: node for node in tree.nodes() if isinstance(node, FunctionDef)
    }
    return tree, context, functions


def _calls(tree, name: str):
    return tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Call) and getattr(node.func, "id", None) == name
    )


def _edge(outcome) -> CallSiteValue:
    """A same-file call's value: its coordinate and edge, completing under
    its ``completes`` atom and halting under the complement."""
    assert isinstance(outcome, ExitSet), type(outcome)
    assert outcome.halts(), outcome
    (completed,) = [face for face in outcome.exits if isinstance(face, Completed)]
    assert isinstance(completed.value, CallSiteValue), type(completed.value)
    return completed.value


def _row_return(function):
    """The one value ``function``'s own contract row returns."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    universe = function_universe_outcome(function).completed_value()
    assert universe is not None
    (returned,) = [
        entry for entry in universe.record.statements if isinstance(entry, ReturnValue)
    ]
    return returned.value


def test_two_calls_of_one_function_are_two_edges_with_their_own_actuals() -> None:
    """``choose(2)`` is 3 and ``choose(0)`` is 1: decided at prove, by
    joining ``choose``'s contract and, inside it, ``lower``'s and
    ``upper``'s.  The lift states the two edges and the callees' returns."""
    tree, _, functions = _tree("choose(2)\nchoose(0)\n")
    truthful, lying = (
        _edge(call.sugar().desugar(None)) for call in _calls(tree, "choose")
    )
    assert truthful.arg_values == (TermValue(2),)
    assert lying.arg_values == (TermValue(0),)
    assert _row_return(functions["lower"]) == TermValue(1)
    assert _row_return(functions["upper"]) == TermValue(3)


def test_a_call_that_raises_in_its_callee_names_no_type_at_lift() -> None:
    """``exceptional(2)`` raises ``TypeError`` (``None < 2``).  The call is
    its edge: its halt is the unanswered call's complement face, whose
    exception type nothing at the lift decides.  The type is decided at
    prove from the callee's contract (step 7, #8749); this used to read the
    callee body's ``TypeError`` at the call."""
    tree, _, _ = _tree("exceptional(2)\n")
    (call,) = _calls(tree, "exceptional")
    outcome = call.sugar().desugar(None)
    _edge(outcome)
    assert [halt.effect.exception_name for halt in outcome.halts()] == [None]


def test_identity_over_a_call_result_owes_only_the_calls_own_halts() -> None:
    """``absent() is value`` never raises: ``is`` adds no halt and no
    deferred operation.  The only halts are the calls' own (each same-file
    call halts under the complement of its ``completes`` atom, decided at
    prove)."""
    _, _, functions = _tree()
    outcome = functions["identity_control"].sugar().desugar(None)

    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    assert isinstance(outcome, ExitSet)
    assert any(isinstance(face, Completed) for face in outcome.exits)
    for halt in outcome.halts():
        owner = str(getattr(halt.effect, "producer_node_owner", "") or "")
        assert not owner.startswith("UndecidedCompare"), halt.effect
        assert halt.effect.exception_name is None, halt.effect
