"""Each ``next`` of an iterator the reduction does not step keeps its halt
(#7757, a halt is never dropped; recorded on #8832).

A ``for`` run as its recurrence and a comprehension's symbolic fold iterate
an iterable whose members are not in hand.  Both run ``iter`` once and then a
``next`` per item, through the one iterator path they share
(``iterator_operation.iterated`` and ``iterator_operation.stepped``).  An
iterator's ``__next__`` -- a generator's body, a user ``__next__``, a file --
may raise something other than ``StopIteration`` on any step, so each step
has three faces: its ``StopIteration`` (the iteration ends), its value (the
item runs), and its halt (an undecided raise, owed).  The halt was carried by
neither the loop nor the comprehension before.

Where the iteration's type is decided and its ``__next__`` cannot raise -- a
list, tuple, ``str``, ``bytes``, set or dict, or their iterators -- no
``next`` halt is added.

Each program has a truthful source, which completes, and a lying one, which
claims a completion only a dropped ``next`` halt would give.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

# The owner of the halt ``next`` of an undecided iterator states
# (``FloorValue.undecided_next`` over the iterator ``iter`` completed with).
_NEXT_HALT_OWNER = "SymbolicValue.next"


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


def _next_halts(outcome) -> list:
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    return [
        face
        for face in outcome.halts()
        if type(face.effect) is UndeterminedRaiseEffect
        and face.effect.producer_node_owner == _NEXT_HALT_OWNER
    ]


def _faces(outcome) -> tuple[int, int]:
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    return (
        sum(isinstance(face, Completed) for face in outcome.exits),
        sum(isinstance(face, Halted) for face in outcome.exits),
    )


_GENERATOR = (
    "def gen():\n"
    "    yield 1\n"
    '    raise ValueError("boom")\n'
    "\n"
    "\n"
)

_MAKE = "def make():\n    return [1]\n\n\n"

# name -> source that iterates an iterator whose ``__next__`` is not decided.
_UNDECIDED = {
    "comprehension-over-a-generator": (
        _GENERATOR + "def test_it():\n    ys = [y for y in gen()]\n    assert True\n"
    ),
    "loop-over-a-generator": (
        _GENERATOR
        + "def test_it():\n    for y in gen():\n        pass\n    assert True\n"
    ),
    "comprehension-over-a-call-result": (
        _MAKE + "def test_it():\n    ys = [y for y in make()]\n    assert True\n"
    ),
    "loop-over-a-call-result": (
        _MAKE + "def test_it():\n    for y in make():\n        pass\n    assert True\n"
    ),
    "comprehension-over-a-formal": (
        "def test_it(xs):\n    ys = [y for y in xs]\n    assert True\n"
    ),
    "loop-over-a-formal": (
        "def test_it(xs):\n    for y in xs:\n        pass\n    assert True\n"
    ),
}


@pytest.mark.parametrize("name", sorted(_UNDECIDED))
def test_each_next_of_an_undecided_iterator_keeps_its_halt(name: str) -> None:
    # LYING, read at the reduction: "every step goes on" holds only if the
    # halt of ``next`` were dropped.  It is kept, beside the completion.
    outcome = _outcome(_UNDECIDED[name])

    completed, halted = _faces(outcome)
    assert completed >= 1, outcome
    assert halted >= 1, outcome
    assert _next_halts(outcome), outcome.halts()


# name -> source that iterates a value whose ``next`` is decided never to
# raise.
_DECIDED = {
    "comprehension-over-a-list": (
        "def test_it():\n    xs = [1, 2]\n    ys = [y for y in xs]\n    assert True\n"
    ),
    "comprehension-over-a-tuple": (
        "def test_it():\n    xs = (1, 2)\n    ys = [y for y in xs]\n    assert True\n"
    ),
    "comprehension-over-a-str": (
        'def test_it():\n    ys = [c for c in "ab"]\n    assert True\n'
    ),
    "loop-over-a-list": (
        "def test_it():\n"
        "    xs = [1, 2]\n"
        "    for y in xs:\n"
        "        pass\n"
        "    assert True\n"
    ),
}


@pytest.mark.parametrize("name", sorted(_DECIDED))
def test_next_of_a_decided_iterator_adds_no_halt(name: str) -> None:
    # TRUTHFUL: a list, tuple or ``str`` iterator's ``__next__`` cannot raise.
    outcome = _outcome(_DECIDED[name])

    assert not _next_halts(outcome), outcome.halts()
    assert _faces(outcome) == (1, 0)


# The lie iterates a same-file generator whose body raises after one yield:
# ``test_it`` completes only where every ``next`` of it does.
_SOLVER_LIE = _UNDECIDED["comprehension-over-a-generator"]
_LIE_TEST_LINE = 6
_SOLVER_TRUTH = (
    "def test_it():\n    ys = [i for i in range(3)]\n    assert ys == [0, 1, 2]\n"
)


def test_a_dropped_next_halt_would_read_sat(tmp_path: Path) -> None:
    """Through real ``sugar mint`` and ``sugar prove``.

    The lie claims ``test_it`` completes, which it does only where each
    ``next`` of ``gen()``'s iterator completes: its ``__next__`` is the
    generator's body, joined at prove, so each ``next`` is the undecided
    read it owes (step 8, ``undecided``) and halts under the complement of
    its completes atom.  Never ``sat``.  The truthful source iterates
    ``range(3)``, whose members the reduction holds: the list is decided,
    nothing is owed, and the claim is ``sat``."""
    lying = run_source_through_real_solver(tmp_path / "l", _SOLVER_LIE)
    truthful = run_source_through_real_solver(tmp_path / "t", _SOLVER_TRUTH)

    assert lying.verdict != "sat"
    assert claim_verdict(lying.prove_doc, claims_from_line=_LIE_TEST_LINE) != "sat"
    assert truthful.verdict == "sat"
