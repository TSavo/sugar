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
y``) exposed a carrier bug: an ``IfExp`` short circuit's stopping face was
unioned in only at the very end of discharge, so the work enrolled after it
(the ``return``, the block projection) ran on the continuing leg only. The
stopping leg reached the block reducer as a bare ``TermValue(0)``. A short
circuit is now unioned in where it was recorded, so every later step runs on
both legs.
"""

from __future__ import annotations

import pytest
from frame_fresh import fresh

from sugar_lift_py_tests.floor import (
    BytesValue,
    ListValue,
    NoneValue,
    SetValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.ir import atomic

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile

GUARD = atomic("renamed_guard", [])


def _helper_outcome(source: str):
    """The helper lifted on its own: formal operands stay deferred carriers."""
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


def _discharged_returns(source: str, actual: int):
    """``(guard, returned value)`` of every completed face after discharge."""
    pending = _helper_outcome(source)
    (formal,) = [cid for cid in pending.demand.operand_coordinate_cids if cid]
    exits = pending.discharge(None, {formal: TermValue(actual)})
    returns = []
    halts = []
    for face in exits.exits:
        if not isinstance(face, Completed):
            # The guard's halts return nothing.
            halts.append(face.effect.producer_node_owner)
            continue
        for entry in face.value.record.statements:
            if isinstance(entry, ReturnValue):
                returns.extend(_returned(face.guard, entry.value))
            elif type(entry).__name__ == "GuardedReturn":
                returns.extend(_returned(entry.guards, entry.value))
    assert sorted(halts) == _GUARD_HALTS
    return returns


def test_a_formal_store_in_an_undecided_suite_discharges() -> None:
    returns = _discharged_returns(_source("r[0] = -x", "x"), 3)
    # By value (``allocation`` is provenance, not compared), never by repr.
    values = [value for _guard, value in returns]
    expected = [
        fresh(ListValue, (TermValue(-3),)),
        fresh(ListValue, (TermValue(0),)),
    ]
    assert len(values) == len(expected)
    assert all(value in values for value in expected)


def test_a_formal_append_in_an_undecided_suite_discharges() -> None:
    returns = _discharged_returns(_source("r.append(-x)", "x"), 3)
    # By value (``allocation`` is provenance, not compared), never by repr.
    values = [value for _guard, value in returns]
    expected = [
        fresh(ListValue, (TermValue(0), TermValue(-3))),
        fresh(ListValue, (TermValue(0),)),
    ]
    assert len(values) == len(expected)
    assert all(value in values for value in expected)


def test_a_formal_expression_statement_in_an_undecided_suite_discharges() -> None:
    source = (
        "import textwrap\n"
        "def helper(x):\n"
        "    if textwrap.dedent('a'):\n"
        "        -x\n"
        "    return 1\n"
    )
    returns = _discharged_returns(source, 3)
    assert returns and all(value == TermValue(1) for _guard, value in returns)


def test_the_stopping_leg_of_a_joined_name_reaches_the_return() -> None:
    """``y`` is ``-x if c else 0`` after the join: both legs are returned."""
    source = (
        "import textwrap\n"
        "def helper(x):\n"
        "    y = 0\n"
        "    if textwrap.dedent('a'):\n"
        "        y = -x\n"
        "    return y\n"
    )
    returns = _discharged_returns(source, 3)
    by_value = {value.value: guard for guard, value in returns}
    assert sorted(by_value) == [-3, 0]
    # ``y`` is one value joined under the ``if``: the deferred leg is its
    # true arm and the stopping leg its false arm, under one join guard, so
    # neither value is claimed on the other's path.  Both stand on the one
    # face where ``textwrap.dedent`` completed.
    then_face, then_join, then_polarity = by_value[-3]
    else_face, else_join, else_polarity = by_value[0]
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
