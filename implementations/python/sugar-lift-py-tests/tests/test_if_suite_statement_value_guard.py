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
    """It lifts; its only halt is ``textwrap.dedent``'s own may-raise face.

    ``textwrap`` is not enrolled here, so the guard's call is an unknown
    callee: it completes under an opaque atom or raises under its complement.
    """
    outcome = _helper_outcome(_source(body))
    faces = outcome.exits
    assert any(isinstance(face, Completed) for face in faces)
    assert [
        face.effect.producer_node_owner
        for face in faces
        if not isinstance(face, Completed)
    ] == ["UnknownCallee:textwrap.dedent"]


def _discharged_returns(source: str, actual: int):
    """``(guard, returned value)`` of every completed face after discharge."""
    pending = _helper_outcome(source)
    (formal,) = [cid for cid in pending.demand.operand_coordinate_cids if cid]
    exits = pending.discharge(None, {formal: TermValue(actual)})
    returns = []
    for face in exits.exits:
        if not isinstance(face, Completed):
            # The unenrolled guard call's own may-raise face returns nothing.
            assert face.effect.producer_node_owner == "UnknownCallee:textwrap.dedent"
            continue
        for entry in face.value.record.statements:
            if isinstance(entry, ReturnValue):
                returns.append((face.guard, entry.value))
            elif type(entry).__name__ == "GuardedReturn":
                returns.append((entry.guards, entry.value))
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
    # The stopping leg stands under the complement of the deferred leg's
    # guard: neither value is claimed on the other's path.
    then_guard, else_guard = (
        _within_dedent_completion(by_value[-3]),
        _within_dedent_completion(by_value[0]),
    )
    assert getattr(else_guard, "kind", None) == "not"
    assert else_guard.operands == (then_guard,)


def _within_dedent_completion(guard):
    """Both legs stand where ``textwrap.dedent`` completed: strip that atom."""
    assert guard.kind == "and", guard
    completion, inner = guard.operands
    assert completion.name == "python:unknown_callee_call.completes"
    assert completion.args[0].args[0].value == "textwrap.dedent"
    return inner
