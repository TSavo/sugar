"""Test doors for the deliberately non-projectable native-operation carrier,
and for the undecided two faces an operator on a parameter is instead."""

import pytest

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.ir import _Atomic
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.outcome.exit_set import _is_true


def completed_function_value(function):
    """Project only an outcome that really completed; never accept a carrier."""
    outcome = function.sugar().desugar()
    assert isinstance(outcome, ExitSet), outcome
    value = outcome.completed_value()
    assert value is not None, outcome
    return value


def native_carrier_for(function, *, operator):
    """Pin the pending operation and prove that it has no value projection."""
    outcome = function.sugar().desugar()
    assert isinstance(outcome, NativeOperationExitCarrierV1), outcome
    with pytest.raises(AttributeError, match="value"):
        _ = outcome.value
    assert outcome.demand.operator == operator
    return outcome


def undecided_outcome(function):
    """A function whose body runs a binary, in-place or comparison operator
    on a parameter (``p == q``, ``p < 3``, ``p + 1``, ``x in p``): no carrier
    waits on a caller; the operation is the undecided two faces where it
    runs, which owe the undecided member (#7757, audit row NEW-1)."""
    outcome = function.sugar().desugar()
    assert isinstance(outcome, ExitSet), outcome
    assert outcome.owed_items(), outcome
    return outcome


def undetermined_owners(outcome):
    """The producer of each halt with no named exception type, in order."""
    return tuple(
        halt.effect.producer_node_owner
        for halt in outcome.halts()
        if isinstance(halt.effect, UndeterminedRaiseEffect)
    )


def atoms_named(outcome, name):
    """Every ``name`` atom in the guards of ``outcome``'s arms, in order."""
    found = []

    def walk(node):
        if isinstance(node, _Atomic):
            if node.name == name:
                found.append(node)
            return
        for child in getattr(node, "operands", ()):
            walk(child)
        body = getattr(node, "body", None)
        if body is not None:
            walk(body)

    for exit_ in outcome.exits:
        walk(exit_.guard)
    return tuple(found)


def undecided_function_value(function, *, owner):
    """The one completed arm of the undecided two faces.

    It completes only under its own completes atom (never under truth), and
    the operation's halt (an ``UndeterminedRaiseEffect`` by ``owner``) is
    kept beside it: no exception type is named and no completion stands
    alone."""
    outcome = undecided_outcome(function)
    assert owner in undetermined_owners(outcome), outcome.exits
    completed = tuple(
        exit_ for exit_ in outcome.normalize().exits if isinstance(exit_, Completed)
    )
    assert len(completed) == 1, outcome.exits
    assert not _is_true(completed[0].guard), completed[0].guard
    return completed[0].value
