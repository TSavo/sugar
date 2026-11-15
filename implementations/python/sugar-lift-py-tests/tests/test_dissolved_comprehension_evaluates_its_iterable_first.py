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

The member that raises is ``int("x")``, a builtin the reduction decides over
its ground operand (``ValueError``, always), and the element is ``1 // x``,
decided over the first member ``0`` (``ZeroDivisionError``).  The programs
used same-file helpers (``boom()``, ``inv(zero())``) until #7757 steps 5 and
6 (#8705): a same-file call is now its coordinate and edge, whose raise is
decided at prove, never at the reduction, so the order the reduction keeps
could no longer be read off which exception the ``try`` caught.  A builtin
call is a member that runs code all the same (``_evaluates_code``).
"""

from __future__ import annotations

import pytest

# name -> (body of ``def test_it():`` with ``{claim}``, Python's value, the lie)
#
# Python raises ``int("x")``'s ``ValueError`` while it evaluates the
# iterable, before any element runs: ``ok`` is 1.  The interleaved order ran
# ``1 // 0`` first and raised ``ZeroDivisionError``: ``ok`` was 2.
_PROGRAMS = {
    "list-comprehension": (
        "    ok = 0\n"
        "    try:\n"
        '        r = [1 // x for x in [0, int("x")]]\n'
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
        '        for y in [1 // x for x in [0, int("x")]]:\n'
        "            pass\n"
        "    except ValueError:\n"
        "        ok = 1\n"
        "    except ZeroDivisionError:\n"
        "        ok = 2\n"
        "    assert ok == {claim}\n",
        "1",
        "2",
    ),
    # An unpack consumes the dissolved display member by member
    # (``Assign._unpacked_in_order``): what the display carries is evaluated
    # before its first member.
    "unpack-of-a-dissolved-comprehension": (
        "    ok = 0\n"
        "    try:\n"
        '        a, b = [1 // x for x in [0, int("x")]]\n'
        "    except ValueError:\n"
        "        ok = 1\n"
        "    except ZeroDivisionError:\n"
        "        ok = 2\n"
        "    assert ok == {claim}\n",
        "1",
        "2",
    ),
    # A dict comprehension's repeated key: Python evaluates the earlier
    # pair (its value raises here) before the later one overwrites it.  The
    # dissolve dropped the earlier pair, so the dict was built and ``ok``
    # stayed 0.
    "dict-comprehension-repeated-key": (
        "    ok = 0\n"
        "    try:\n"
        '        d = {{0: int("x") if x == 0 else x for x in range(2)}}\n'
        "    except ValueError:\n"
        "        ok = 1\n"
        "    assert ok == {claim}\n",
        "1",
        "0",
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

    source = "def test_it():\n" + body
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
    # ``int("x")``'s ``ValueError`` is raised before the element ever runs.
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    body, truthful, _lying = _PROGRAMS[name]
    function = _function(body.format(claim=truthful))

    assert _faces(function_universe_outcome(function)) == (1, 0)


@pytest.mark.parametrize("name", sorted(_PROGRAMS))
def test_the_lying_claim_does_not_complete(name: str) -> None:
    # LYING: ``1 // 0`` evaluated before ``int("x")`` -- the element
    # interleaved with the iterable -- raises ``ZeroDivisionError``.
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    body, _truthful, lying = _PROGRAMS[name]
    function = _function(body.format(claim=lying))

    completed, halted = _faces(function_universe_outcome(function))
    assert completed == 0
    assert halted >= 1
