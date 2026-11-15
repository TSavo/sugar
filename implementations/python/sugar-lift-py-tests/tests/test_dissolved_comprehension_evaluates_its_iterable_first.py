"""A dissolved comprehension evaluates its iterable display before any element
(#7757, surfaced by #8670).

Python evaluates a comprehension's iterable -- every member of a display --
once, before the first element.  A comprehension the unroll dissolves into a
display substituted each member into the element, so ``[h(x) for x in [g1(),
g2()]]`` was evaluated g1, h, g2, h.  Where ``h(g1())`` raises and ``g2()``
raises something else, the dissolved display halted with ``h``'s exception
where Python halts with ``g2``'s.  Each member that runs code is now evaluated
before the first element, in order, its value held under its item key, and
the element reads it there (``ListComp._members_evaluated_first``); an
unrolled ``for`` over the dissolved display evaluates them the same way
(``For._iterable_evaluated``).

Each program has a truthful claim (what Python computes), which must
complete, and a lying claim (what the interleaved order computed), which must
not.
"""

from __future__ import annotations

import pytest

_HELPERS = (
    "def zero():\n"
    "    return 0\n"
    "\n"
    "\n"
    "def boom():\n"
    "    raise ValueError\n"
    "\n"
    "\n"
    "def inv(x):\n"
    "    return 1 // x\n"
    "\n"
    "\n"
)

# name -> (body of ``def test_it():`` with ``{claim}``, Python's value, the lie)
#
# Python raises ``boom()``'s ``ValueError`` while it evaluates the iterable,
# before any element runs: ``ok`` is 1.  The interleaved order ran
# ``inv(zero())`` first and raised ``ZeroDivisionError``: ``ok`` was 2.
_PROGRAMS = {
    "list-comprehension": (
        "    ok = 0\n"
        "    try:\n"
        "        r = [inv(x) for x in [zero(), boom()]]\n"
        "    except ValueError:\n"
        "        ok = 1\n"
        "    except ZeroDivisionError:\n"
        "        ok = 2\n"
        "    assert ok == {claim}\n",
        "1",
        "2",
    ),
    "loop-over-a-dissolved-comprehension": (
        "    ok = 0\n"
        "    try:\n"
        "        for y in [inv(x) for x in [zero(), boom()]]:\n"
        "            pass\n"
        "    except ValueError:\n"
        "        ok = 1\n"
        "    except ZeroDivisionError:\n"
        "        ok = 2\n"
        "    assert ok == {claim}\n",
        "1",
        "2",
    ),
}


def _function(body: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree import nodes
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile

    source = _HELPERS + "def test_it():\n" + body
    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        reporter=CollectingReporter(),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, nodes.FunctionDef) and node.name == "test_it"
    )
    return function


def _faces(outcome) -> tuple[int, int]:
    """(completed faces, halted faces) of a function's universe outcome."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    return (
        sum(isinstance(face, Completed) for face in outcome.exits),
        sum(isinstance(face, Halted) for face in outcome.exits),
    )


@pytest.mark.parametrize("name", sorted(_PROGRAMS))
def test_the_truthful_claim_completes(name: str) -> None:
    # TRUTHFUL: the iterable's members are evaluated first, in order, so
    # ``boom()``'s ``ValueError`` is raised before ``inv`` ever runs.
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    body, truthful, _lying = _PROGRAMS[name]
    function = _function(body.format(claim=truthful))

    assert _faces(function_universe_outcome(function)) == (1, 0)


@pytest.mark.parametrize("name", sorted(_PROGRAMS))
def test_the_lying_claim_does_not_complete(name: str) -> None:
    # LYING: ``inv(zero())`` evaluated before ``boom()`` -- the element
    # interleaved with the iterable -- raises ``ZeroDivisionError``.
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    body, _truthful, lying = _PROGRAMS[name]
    function = _function(body.format(claim=lying))

    completed, halted = _faces(function_universe_outcome(function))
    assert completed == 0
    assert halted >= 1
