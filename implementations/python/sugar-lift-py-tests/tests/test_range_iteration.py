"""A completed ``range(...)`` call's value is a range object, whose iteration
never raises; the call's own raises are its halt faces (#7757, recorded on
#8832).

``range(n)``'s value is the call's result (a ``CallSiteValue``), so a loop or
comprehension over it ran ``iter`` and ``next`` as the undecided reads of an
iterator nothing decides, and each added a halt and an owed member.  CPython's
``range`` returns a range object or raises -- ``TypeError`` for a non-int
operand, a keyword actual or a wrong arity, ``ValueError`` for a zero step --
so on every face the call completes on its value is a range object
(``source_call_resolution._range_object``, read off the call's binding), and
iterating one never raises (``iterates_without_raising``).  The call's own
raises stay its halt faces: the cited fold decides them over ground operands
(``range(0, n, 0)`` with ``n`` decided is the one ``ValueError``), and over an
operand nothing decides (a formal) they are the halt of the one two-faced
unanswered call (owner ``UnknownCallee:range``).

Each program has a truthful source, which completes, and a lying one, which
claims a completion only a dropped ``range`` halt would give.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

# The owners of the halts iterating an undecided iterable states: ``iter``
# (over a formal with no actual, any other symbolic value, a call's result)
# and ``next`` of the iterator it completed with.
_ITERATION_HALT_OWNERS = frozenset(
    {
        "UnansweredNativeOperation:iter",
        "SymbolicValue.iter",
        "CallSiteValue.iter",
        "SymbolicValue.next",
    }
)
# The owner of the halt of ``range``'s own call over an operand nothing
# decides (``UnknownCalleeCallV1``).
_RANGE_CALL_OWNER = "UnknownCallee:range"


def _function(source: str, name: str = "test_it"):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree import nodes
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        reporter=CollectingReporter(),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, nodes.FunctionDef) and node.name == name
    )
    return function


def _outcome(source: str):
    """The function's outcome as its own proof states it."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    return function_universe_outcome(_function(source))


def _owners(outcome) -> list:
    return [
        getattr(face.effect, "producer_node_owner", None) for face in outcome.halts()
    ]


def _faces(outcome) -> tuple[int, int]:
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    return (
        sum(isinstance(face, Completed) for face in outcome.exits),
        sum(isinstance(face, Halted) for face in outcome.exits),
    )


# name -> source iterating ``range`` over decided int operands.  ``n`` is
# decided (``len`` of a list display, folded at the reduction) but no
# literal, so the construction does not unroll the range: the loop and the
# comprehension iterate the call's result.
_DECIDED = {
    "comprehension": (
        "def test_it():\n"
        "    n = len([1, 2, 3])\n"
        "    ys = [i for i in range(n)]\n"
        "    assert True\n"
    ),
    "set-comprehension": (
        "def test_it():\n"
        "    n = len([1, 2, 3])\n"
        "    ys = {i for i in range(n)}\n"
        "    assert True\n"
    ),
    "loop": (
        "def test_it():\n"
        "    n = len([1, 2, 3])\n"
        "    for i in range(n):\n"
        "        pass\n"
        "    assert True\n"
    ),
}


@pytest.mark.parametrize("name", sorted(_DECIDED))
def test_iterating_a_decided_range_adds_no_halt(name: str) -> None:
    # TRUTHFUL: ``range(3)`` completes with a range object, and iterating it
    # never raises.
    outcome = _outcome(_DECIDED[name])

    assert not set(_owners(outcome)) & _ITERATION_HALT_OWNERS, outcome.halts()
    # No halt at all; a loop's recurrence may leave by more than one
    # completed arm (no item ran, an item ran).
    completed, halted = _faces(outcome)
    assert halted == 0, outcome.halts()
    assert completed >= 1, outcome


# name -> source iterating ``range`` over a formal: the call's own halt is
# kept; iterating its value adds none.
_FORMAL = {
    "comprehension": (
        "def test_it(n):\n    ys = [i for i in range(n)]\n    assert True\n"
    ),
    "loop": (
        "def test_it(n):\n    for i in range(n):\n        pass\n    assert True\n"
    ),
}


@pytest.mark.parametrize("name", sorted(_FORMAL))
def test_range_over_a_formal_keeps_its_own_halt_only(name: str) -> None:
    # LYING, read at the reduction: "it always completes" holds only if
    # ``range``'s own raise (a non-int ``n``, its ``__index__``) were
    # dropped.  It is kept; iterating the range object it completes with
    # adds no halt.
    outcome = _outcome(_FORMAL[name])

    owners = _owners(outcome)
    assert _RANGE_CALL_OWNER in owners, outcome.halts()
    assert not set(owners) & _ITERATION_HALT_OWNERS, outcome.halts()
    completed, _halted = _faces(outcome)
    assert completed >= 1, outcome


# The decided ``range`` the solver twin iterates, and the same call with a
# zero step, which CPython refuses with ``ValueError`` before any item.
#
# The solver twin iterates by a ``for``, never a comprehension: a
# comprehension over a range object is its symbolic fold (the range is no
# finite container, ``comprehension_sugar._finite_members``), and the fold
# completing is its read, owed as the undecided member (#8916, step 6), so
# the comprehension's truthful source reads ``open`` whatever ``range`` does
# (scorecard at d95c22a49: the test row discharged beside the fold's and the
# member's owed rows).  A loop that reads neither its item nor a carried name
# owes nothing, so the twin asks only about ``range``'s halts.
#
# Its claim is a same-file call prove decides (``three() == 3``, joined to
# ``three``'s contract), never ``assert True``: the live loop states its
# target's recurrence (``python:loop.recurrence = python:loop.step(...)``,
# ``LoopRecurrenceSugar._recurrence``) in the row, a decided ``True`` folds
# away, and the row was that one opaque equation alone, which the vacuity
# guard refuses (scorecard at d707d3fb5: the truthful row ``refused``,
# "single constraint has no sibling to contradict", nothing owed).  The
# claim prove decides is the row's sibling.  The three sources differ only
# in the ``range`` they iterate.
_SOLVER_HELPER = "def three():\n    return 3\n\n\n"
# The test function's ``def`` follows the helper.
_SOLVER_TEST_LINE = _SOLVER_HELPER.count("\n") + 1
_SOLVER_TRUTH = _SOLVER_HELPER + (
    "def test_it():\n"
    "    n = len([1, 2, 3])\n"
    "    for i in range(n):\n"
    "        pass\n"
    "    assert three() == 3\n"
)
_SOLVER_ZERO_STEP = _SOLVER_HELPER + (
    "def test_it():\n"
    "    n = len([1, 2, 3])\n"
    "    for i in range(0, n, 0):\n"
    "        pass\n"
    "    assert three() == 3\n"
)
_SOLVER_FORMAL = _SOLVER_HELPER + (
    "def test_it(n):\n"
    "    for i in range(n):\n"
    "        pass\n"
    "    assert three() == 3\n"
)


def test_a_dropped_range_halt_would_read_sat(tmp_path: Path) -> None:
    """Through real ``sugar mint`` and ``sugar prove``.

    The truthful source iterates ``range(n)`` with ``n`` decided: the call
    completes with a range object, iterating it never raises, nothing is
    owed, and the claim is ``sat``.  The lies claim a completion only a
    dropped ``range`` halt would give: a zero step is the cited fold's one
    ``ValueError``, and ``range`` over a formal is the one unanswered call,
    owed.  Neither is ever ``sat``."""
    truthful = run_source_through_real_solver(tmp_path / "t", _SOLVER_TRUTH)
    zero_step = run_source_through_real_solver(tmp_path / "z", _SOLVER_ZERO_STEP)
    formal = run_source_through_real_solver(tmp_path / "f", _SOLVER_FORMAL)

    assert (
        claim_verdict(truthful.prove_doc, claims_from_line=_SOLVER_TEST_LINE) == "sat"
    )
    assert zero_step.verdict != "sat"
    assert (
        claim_verdict(zero_step.prove_doc, claims_from_line=_SOLVER_TEST_LINE) != "sat"
    )
    assert formal.verdict != "sat"
    assert claim_verdict(formal.prove_doc, claims_from_line=_SOLVER_TEST_LINE) != "sat"
