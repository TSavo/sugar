"""A symbolic comprehension states that iterating its iterable may raise
(#7757, a halt is never dropped; surfaced by #8809).

A comprehension runs ``iter`` on its iterable before any member, as a ``for``
does.  Over an iterable whose ``__iter__`` is not decided here -- a formal, a
call's result, a symbolic member of an outer generator -- that ``iter`` may
raise.  The symbolic fold submits the one ``iter`` operation
(``IteratorOperation``) to the iterable, as the loop does
(``LoopRecurrenceSugar._desugar_with_iterable``): a formal's waits on its
caller's actual, any other undecided receiver is the one two-faced read
(``FloorValue.undecided_iteration``).  The fold follows the face ``iter``
completes on; the face it raises on is kept.

Where iterating the iterable is decided never to raise -- a list, tuple,
dict, set or ``str`` in hand (``iterator_operation.iteration_total``) --
no halt face is added.

Each program has a truthful source, which completes, and a lying one, which
claims a completion only a dropped iteration halt would give.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

# The owners of the halt ``iter`` of an undecided iterable states: a formal
# with no actual (its function's own proof), any other symbolic value, a
# call's result.
_ITERATION_HALT_OWNERS = frozenset(
    {
        "UnansweredNativeOperation:iter",
        "SymbolicValue.iter",
        "CallSiteValue.iter",
    }
)


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


def _iteration_halts(outcome) -> list:
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    return [
        face
        for face in outcome.halts()
        if type(face.effect) is UndeterminedRaiseEffect
        and face.effect.producer_node_owner in _ITERATION_HALT_OWNERS
    ]


def _faces(outcome) -> tuple[int, int]:
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    return (
        sum(isinstance(face, Completed) for face in outcome.exits),
        sum(isinstance(face, Halted) for face in outcome.exits),
    )


# name -> source whose comprehension iterates something ``iter`` may raise on.
_UNDECIDED = {
    "list-over-a-formal": (
        "def test_it(xs):\n    ys = [y for y in xs]\n    assert True\n"
    ),
    "set-over-a-formal": (
        "def test_it(xs):\n    ys = {y for y in xs}\n    assert True\n"
    ),
    "dict-over-a-formal": (
        "def test_it(xs):\n    ys = {y: y for y in xs}\n    assert True\n"
    ),
    "generator-over-a-formal": (
        "def test_it(xs):\n    ys = list(y for y in xs)\n    assert True\n"
    ),
    "list-over-a-call-result": (
        "def make():\n"
        "    return [1]\n"
        "\n"
        "\n"
        "def test_it():\n"
        "    ys = [y for y in make()]\n"
        "    assert True\n"
    ),
    # The inner generator iterates each outer member, whose type the fold
    # does not decide, even over a decided outer list.
    "inner-generator-over-a-member": (
        "def test_it(rows):\n"
        "    ys = [y for row in rows for y in row]\n"
        "    assert True\n"
    ),
}


@pytest.mark.parametrize("name", sorted(_UNDECIDED))
def test_iterating_an_undecided_iterable_keeps_its_halt(name: str) -> None:
    # LYING, read at the reduction: "it always completes" holds only if the
    # halt of ``iter`` were dropped.  It is kept, beside the completion.
    outcome = _outcome(_UNDECIDED[name])

    completed, halted = _faces(outcome)
    assert completed >= 1, outcome
    assert halted >= 1, outcome
    assert _iteration_halts(outcome), outcome.halts()


# name -> source whose comprehension iterates a value whose iteration is
# decided never to raise.
_DECIDED = {
    "list-display": (
        "def test_it():\n    xs = [1, 2]\n    ys = [y for y in xs]\n    assert True\n"
    ),
    "tuple-display": (
        "def test_it():\n    xs = (1, 2)\n    ys = [y for y in xs]\n    assert True\n"
    ),
    # A ``str`` is no finite container here: the comprehension stays the
    # symbolic fold, and states no iteration halt over it.
    "str-constant": (
        'def test_it():\n    ys = [c for c in "ab"]\n    assert True\n'
    ),
}


@pytest.mark.parametrize("name", sorted(_DECIDED))
def test_iterating_a_decided_iterable_adds_no_halt(name: str) -> None:
    # TRUTHFUL: iterating a list, a tuple or a ``str`` cannot raise.
    assert _faces(_outcome(_DECIDED[name])) == (1, 0)


# The solver twin differs in where ``xs`` comes from: a formal (``iter`` not
# decided) or a list the function builds (``iter`` cannot raise).
_SOLVER_LIE = "def test_it(xs):\n    ys = [y for y in xs]\n    assert True\n"
_SOLVER_TRUTH = (
    "def test_it():\n    xs = [1, 2]\n    ys = [y for y in xs]\n    assert True\n"
)


def test_a_dropped_iteration_halt_would_read_sat(tmp_path: Path) -> None:
    """Through real ``sugar mint`` and ``sugar prove``.

    The lie claims ``test_it`` completes, which it does only where
    ``iter(xs)`` completes: ``xs`` is a formal with no actual in the
    function's own proof, so ``iter`` is the operation it owes (step 8,
    ``undecided``) and halts under the complement of its completes atom.
    Never ``sat``.  The truthful source iterates a list it built: nothing is
    owed, and the claim is ``sat``."""
    lying = run_source_through_real_solver(tmp_path / "l", _SOLVER_LIE)
    truthful = run_source_through_real_solver(tmp_path / "t", _SOLVER_TRUTH)

    assert lying.verdict != "sat"
    assert claim_verdict(lying.prove_doc, claims_from_line=1) != "sat"
    assert truthful.verdict == "sat"
