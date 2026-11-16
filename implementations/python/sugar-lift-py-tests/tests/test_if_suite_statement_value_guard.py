"""A suite's statement values ride an undecided ``if`` guard unchanged.

An expression statement records its value (``len(r)`` is ``TermValue(1)``)
and a store records the container it leaves (``r[0] = 5``, ``r.append(5)``
record a ``ListValue``). Under an undecided ``if`` the join guards every
entry, and these pure constructed values had no guard law, so lifting
``if textwrap.dedent('a'): r.append(5)`` panicked with ``implement
ListValue.guarded`` / ``TermValue.guarded``. A value with no invariant,
postcondition, control effect, or scope transition states nothing a guard
could weaken: ``TermValue``, ``ListValue``, ``TupleValue``, ``SetValue``,
``NoneValue`` and ``BytesValue`` join ``StringValue`` and ``DictValue`` as
guard-stable. An obligation still weakens to an implication, and an
unclassified value stays loud (``test_guarded_floor_value_law``).

The same suites over a formal (``y = -x`` under the guard, then ``return
y``) reach the return on both legs. ``-x`` on a parameter is the undecided
two faces (#9018: ``python:unary_result("-", x, <key>)`` under its completes
atom, its ``SymbolicValue.unary_minus`` halt kept), never a carrier waiting
on a caller's actual, so the function's own outcome is read as it stands.
"""

from __future__ import annotations

import pytest
from frame_fresh import fresh

from sugar_lift_py_tests.floor import (
    BytesValue,
    ListValue,
    NoneValue,
    SetValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.ir import atomic, str_const

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile

GUARD = atomic("renamed_guard", [])


def _helper_outcome(source: str):
    """The helper lifted on its own: an operation on a formal is the
    undecided two faces where it runs (#9018), never a deferred carrier."""
    tree = SourceFile(
        (source, "if-suite-statement-value.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function.sugar().desugar(None)


@pytest.mark.parametrize(
    "value",
    (
        TermValue(1),
        fresh(ListValue, (TermValue(1),)),
        TupleValue((TermValue(1),)),
        fresh(SetValue, (TermValue(1),)),
        NoneValue(),
        BytesValue(b"x"),
    ),
    ids=("term", "list", "tuple", "set", "none", "bytes"),
)
def test_pure_container_and_scalar_values_are_guard_stable(value) -> None:
    assert value.guarded(GUARD) is value


def _source(body: str, formals: str = "") -> str:
    return (
        "import textwrap\n"
        f"def helper({formals}):\n"
        "    r = [0]\n"
        "    if textwrap.dedent('a'):\n"
        f"        {body}\n"
        "    return r\n"
    )


@pytest.mark.parametrize(
    "body", ("r[0] = 5", "r.append(5)", "len(r)", "r[0] = -r[0]")
)
def test_a_statement_value_in_an_undecided_suite_lifts(body) -> None:
    """It lifts; its halts are the guard's two may-raise faces.

    ``textwrap`` is not enrolled here, so the guard's call is an unknown
    callee: it completes under an opaque atom or raises under its complement
    (``UnknownCallee:textwrap.dedent``).  What it returns is an object of no
    decided type, so ``bool()`` of it runs that object's ``__bool__`` /
    ``__len__``, which may raise: the ``if`` takes that truth through the one
    truth rule, which completes or halts at the ``if`` (``IfSugar.test``).
    Neither suite runs on either halt.
    """
    outcome = _helper_outcome(_source(body))
    faces = outcome.exits
    assert any(isinstance(face, Completed) for face in faces)
    assert sorted(
        face.effect.producer_node_owner
        for face in faces
        if not isinstance(face, Completed)
    ) == _GUARD_HALTS


# The guard's two halts: the unenrolled call raised, or ``bool()`` of the
# object it returned raised (its type is not decided here).
_GUARD_HALTS = ["IfSugar.test", "UnknownCallee:textwrap.dedent"]


def _returned(guard, value):
    """``(guard, value)`` for one returned value.  A name the undecided ``if``
    joined is one ``GuardedValue``: each arm is returned under the join's
    guard and its own polarity, ``(guard, join guard, True | False)``."""
    if isinstance(value, GuardedValue):
        return [
            *_returned((guard, value.guard, True), value.when_true),
            *_returned((guard, value.guard, False), value.when_false),
        ]
    return [(guard, value)]


# The halt of ``-x`` on the formal in the suite: the undecided unary
# operation's complement (#9018), kept beside the guard's two.
_NEGATION_HALT = "SymbolicValue.unary_minus"


def _negated_formal(value) -> bool:
    """``-x`` over the formal ``x``: the undecided unary result
    ``python:unary_result("-", x, <key>)`` (#9018), never a folded value."""
    term = getattr(value, "term", None)
    return (
        isinstance(value, SymbolicValue)
        and getattr(term, "name", None) == "python:unary_result"
        and term.args[0] == str_const("-")
    )


def _formal_returns(source: str):
    """``(guard, returned value)`` of every completed face of the helper's
    own outcome.  Its halts are the guard's two and the suite's ``-x``."""
    outcome = _helper_outcome(source)
    returns = []
    halts = []
    for face in outcome.exits:
        if not isinstance(face, Completed):
            # The halts return nothing.
            halts.append(face.effect.producer_node_owner)
            continue
        for entry in face.value.record.statements:
            if isinstance(entry, ReturnValue):
                returns.extend(_returned(face.guard, entry.value))
            elif type(entry).__name__ == "GuardedReturn":
                returns.extend(_returned(entry.guards, entry.value))
    assert sorted(halts) == sorted([*_GUARD_HALTS, _NEGATION_HALT]), halts
    return returns


def _left_unchanged_and_the_other(values):
    """The suite-not-taken ``r`` (``[0]``) and the one other returned value."""
    unchanged = fresh(ListValue, (TermValue(0),))
    assert len(values) == 2, values
    assert unchanged in values, values
    (other,) = [value for value in values if value != unchanged]
    return other


def test_a_formal_store_in_an_undecided_suite_reaches_the_return() -> None:
    returns = _formal_returns(_source("r[0] = -x", "x"))
    # By value (``allocation`` is provenance, not compared), never by repr.
    stored = _left_unchanged_and_the_other([value for _guard, value in returns])
    assert isinstance(stored, ListValue), stored
    (element,) = stored.elements
    assert _negated_formal(element), element


def test_a_formal_append_in_an_undecided_suite_reaches_the_return() -> None:
    returns = _formal_returns(_source("r.append(-x)", "x"))
    # By value (``allocation`` is provenance, not compared), never by repr.
    appended = _left_unchanged_and_the_other([value for _guard, value in returns])
    assert isinstance(appended, ListValue), appended
    first, second = appended.elements
    assert first == TermValue(0), appended
    assert _negated_formal(second), second


def test_a_formal_expression_statement_in_an_undecided_suite_reaches_the_return() -> None:
    source = (
        "import textwrap\n"
        "def helper(x):\n"
        "    if textwrap.dedent('a'):\n"
        "        -x\n"
        "    return 1\n"
    )
    returns = _formal_returns(source)
    assert returns and all(value == TermValue(1) for _guard, value in returns)


def test_both_legs_of_a_joined_name_reach_the_return() -> None:
    """``y`` is ``-x if c else 0`` after the join: both legs are returned."""
    source = (
        "import textwrap\n"
        "def helper(x):\n"
        "    y = 0\n"
        "    if textwrap.dedent('a'):\n"
        "        y = -x\n"
        "    return y\n"
    )
    returns = _formal_returns(source)
    assert len(returns) == 2, returns
    (negated,) = [guard for guard, value in returns if _negated_formal(value)]
    (kept,) = [guard for guard, value in returns if value == TermValue(0)]
    # ``y`` is one value joined under the ``if``: the suite's leg is its
    # true arm and the leg that skipped the suite its false arm, under one
    # join guard, so neither value is claimed on the other's path.  Both
    # stand on the one face where ``textwrap.dedent`` completed.
    then_face, then_join, then_polarity = negated
    else_face, else_join, else_polarity = kept
    assert then_face == else_face
    _within_dedent_completion(then_face)
    assert then_join == else_join
    assert (then_polarity, else_polarity) == (True, False)


def _within_dedent_completion(guard):
    """The face stands where ``textwrap.dedent`` completed: its first atom.

    The completion is stated over the call's result, ``python:call_result(
    call:textwrap.dedent(...), <occurrence>)`` (#7757 step 5, #8753), no
    longer over the bare callee name."""
    from sugar_lift_py_tests.call_symbol import call_target

    assert guard.kind == "and", guard
    completion = guard.operands[0]
    assert completion.name == "python:unknown_callee_call.completes"
    (result,) = completion.args
    assert result.name == "python:call_result", result
    assert call_target(result.args[0].name) == "textwrap.dedent", result
