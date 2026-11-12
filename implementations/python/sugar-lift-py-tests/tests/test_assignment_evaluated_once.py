"""Plan row 7 (steps 5 and 6), inventory item 7: the values an assignment's
readers must see, and how many times a callee is applied today.

Substitution replaces a read of ``x`` by the right-hand side of ``x = e``.
Python evaluates ``e`` once, at the statement.  The reducer evaluates it at the
statement and again at every read, unless a record answers the read
(``sugar/assigned_value.py``).  A right-hand side that is one plain completion
is deliberately not recorded, so a callee is applied once per read on top of
once at the statement.

Removing that exception was tried and is wrong with the record's key as it
stands.  The key is ``(type(sugar), site)``, and the copies of one statement in
an unrolled loop share one span, so every iteration's assigned name answered
with the LAST iteration's value: ``total = total + x`` over ``x = i + 1`` for
``i`` in ``(1, 2, 3)`` computed 12 where Python computes 9, and the lying claim
completed.  Today loops are right only because a plain completion never meets
the key.

A second attempt put the dynamic occurrence path (``occurrence.py``) in the
key.  That is wrong too: the path names the READER's dynamic extent.  A
substituted read of an earlier iteration's right-hand side is evaluated inside
the current iteration, so it looks up the site under the current iteration and
finds the current iteration's value.  It passed every program whose claim sits
after the loop and failed the ones whose claim sits inside it
(``_READ_INSIDE_THE_LOOP``).  What a key would need is the evaluation the
right-hand-side COPY belongs to, which neither the span nor the path carries.

These tests are the guard for the next attempt.

- The value tests state what Python computes.  Each program has a truthful
  claim, which must complete, and a lying claim, which must not.  Two
  evaluations of one source span (two iterations, two applications of one
  callee) must never answer for each other.
- The count tests pin how many times a callee's body is reduced today.  Each
  number is today's measured count, not a target.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_HELPERS = (
    "def inc(a):\n"
    "    return a + 1\n"
    "\n"
    "\n"
    "def twice_plus(a):\n"
    "    t = a + 1\n"
    "    return t * 2\n"
    "\n"
    "\n"
    "def tri(n):\n"
    "    s = 0\n"
    "    for d in (1, 2, 3):\n"
    "        t = d * n\n"
    "        s = s + t\n"
    "    return s\n"
    "\n"
    "\n"
    "def down(n):\n"
    "    t = n + 1\n"
    "    if n == 0:\n"
    "        return t\n"
    "    return t * 10 + down(n - 1)\n"
    "\n"
    "\n"
    "class Box:\n"
    "    def __init__(self, n):\n"
    "        self.n = n\n"
    "\n"
    "    def get(self, k):\n"
    "        return self.n + k\n"
    "\n"
    "\n"
)

# name -> (body of ``def test_it():`` with ``{claim}``, what Python computes, a lie)
#
# The lie of each loop program is what the loop computes when every iteration
# reads the last iteration's value.
_PROGRAMS = {
    "box-get": (
        "    a = Box(1)\n    r = a.get(3)\n    assert r == {claim}\n",
        "4",
        "5",
    ),
    "box-get-read-twice": (
        "    a = Box(1)\n    r = a.get(3)\n    assert r + r == {claim}\n",
        "8",
        "9",
    ),
    "unrolled-loop-sum": (
        "    total = 0\n"
        "    for i in (1, 2, 3):\n"
        "        x = i + 1\n"
        "        total = total + x\n"
        "    assert total == {claim}\n",
        "9",
        "12",
    ),
    # Each iteration's ``x`` is read after later iterations assigned theirs.
    "unrolled-loop-digits": (
        "    acc = 0\n"
        "    for i in (1, 2, 3):\n"
        "        x = i + 1\n"
        "        acc = acc * 10 + x\n"
        "    assert acc == {claim}\n",
        "234",
        "444",
    ),
    # ``y`` holds the previous iteration's ``x``.
    "unrolled-loop-previous-value": (
        "    x = 0\n"
        "    y = 0\n"
        "    for i in (1, 2, 3):\n"
        "        y = x\n"
        "        x = i + 1\n"
        "    assert y * 10 + x == {claim}\n",
        "34",
        "44",
    ),
    "nested-unrolled-loops": (
        "    total = 0\n"
        "    for i in (1, 2):\n"
        "        for j in (10, 20):\n"
        "            x = i + j\n"
        "            total = total + x\n"
        "    assert total == {claim}\n",
        "66",
        "88",
    ),
    "nested-unrolled-loops-digits": (
        "    acc = 0\n"
        "    for i in (1, 2):\n"
        "        for j in (3, 4):\n"
        "            x = i * j\n"
        "            acc = acc * 10 + x\n"
        "    assert acc == {claim}\n",
        "3468",
        "8888",
    ),
    "three-nested-loops": (
        "    acc = 0\n"
        "    for i in (0, 1):\n"
        "        for j in (0, 1):\n"
        "            for k in (0, 1):\n"
        "                x = i * 4 + j * 2 + k\n"
        "                acc = acc * 10 + x\n"
        "    assert acc == {claim}\n",
        "1234567",
        "7777777",
    ),
    "unrolled-loop-object": (
        "    acc = 0\n"
        "    for i in (1, 2):\n"
        "        b = Box(i)\n"
        "        r = b.get(1)\n"
        "        acc = acc * 10 + r\n"
        "    assert acc == {claim}\n",
        "23",
        "33",
    ),
    "comprehension-in-a-loop": (
        "    acc = 0\n"
        "    for i in (1, 2):\n"
        "        xs = [i + j for j in (10, 20)]\n"
        "        x = xs[0] + xs[1]\n"
        "        acc = acc * 100 + x\n"
        "    assert acc == {claim}\n",
        "3234",
        "3434",
    ),
    "while-loop": (
        "    n = 0\n"
        "    i = 0\n"
        "    while i < 3:\n"
        "        x = i + 1\n"
        "        n = n * 10 + x\n"
        "        i = i + 1\n"
        "    assert n == {claim}\n",
        "123",
        "333",
    ),
    # The callee has its own loop and its own assignments.
    "function-with-a-loop-called-twice": (
        "    r = tri(1) * 100 + tri(2)\n    assert r == {claim}\n",
        "612",
        "1212",
    ),
    "callee-twice-in-one-expression": (
        "    r = inc(1) + inc(2)\n    assert r == {claim}\n",
        "5",
        "4",
    ),
    "callee-of-callee": ("    r = inc(inc(1))\n    assert r == {claim}\n", "3", "2"),
    "callee-with-a-local-applied-twice": (
        "    r = twice_plus(1) * 10 + twice_plus(2)\n    assert r == {claim}\n",
        "46",
        "66",
    ),
    "callee-with-a-local-assigned-twice": (
        "    a = twice_plus(1)\n    b = twice_plus(2)\n    assert a * 10 + b == {claim}\n",
        "46",
        "66",
    ),
    "same-call-at-two-sites": (
        "    a = inc(1)\n    b = inc(1)\n    assert a + b == {claim}\n",
        "4",
        "5",
    ),
    "rebind": (
        "    x = inc(1)\n    y = x\n    x = inc(2)\n    assert y * 10 + x == {claim}\n",
        "23",
        "33",
    ),
    "rebind-read-between": (
        "    x = inc(1)\n    a = x + x\n    x = inc(2)\n    b = x + x\n"
        "    assert a * 10 + b == {claim}\n",
        "46",
        "66",
    ),
    "plain-constant-read-twice": (
        "    x = 2\n    y = x + x\n    assert y == {claim}\n",
        "4",
        "5",
    ),
}

# An assert INSIDE the loop body reads the accumulator at iteration time, when
# every lookup is made in the current iteration's dynamic extent.  (An assert
# after the loop reads it when nothing is in an iteration, and substitution
# recomputes every copy from scratch.)  Evaluating ``acc * 10 + x`` in
# iteration 2 re-reads iteration 1's ``x``; a record keyed by the site and the
# CURRENT iteration answers that read with iteration 2's ``x``: 33, not 23.
#
# name -> (the loop body's claim that holds in Python, a claim that holds only
#          if every earlier iteration's ``x`` reads as the current one)
_READ_INSIDE_THE_LOOP = {
    "digits": (
        "    acc = 0\n"
        "    for i in (1, 2):\n"
        "        x = i + 1\n"
        "        acc = acc * 10 + x\n"
        "        assert acc == {claim}\n",
        "21 * i - 19",
        "31 * i - 29",
    ),
    "digits-through-a-second-name": (
        "    acc = 0\n"
        "    for i in (1, 2):\n"
        "        x = i + 1\n"
        "        acc = acc * 10 + x\n"
        "        y = acc\n"
        "        assert y == {claim}\n",
        "21 * i - 19",
        "31 * i - 29",
    ),
    "sum": (
        "    total = 0\n"
        "    for i in (1, 2, 3):\n"
        "        x = i + 1\n"
        "        total = total + x\n"
        "        assert total {claim}\n",
        "* 2 == (i + 1) * (i + 2) - 2",
        "== i * (i + 1)",
    ),
}

# A plain function call in the body of an unrolled loop.  These go through the
# real solver: the reduction-level door used above cannot build them (a
# ``BackendDefect``, "producer reporter owns no registration table").
_SOLVER_PROGRAMS = {
    "box-get": _PROGRAMS["box-get"],
    "unrolled-loop-callee": (
        "    total = 0\n"
        "    for i in (1, 2, 3):\n"
        "        x = inc(i)\n"
        "        total = total + x\n"
        "    assert total == {claim}\n",
        "9",
        "12",
    ),
    "unrolled-loop-callee-digits": (
        "    acc = 0\n"
        "    for i in (1, 2, 3):\n"
        "        x = inc(i)\n"
        "        acc = acc * 10 + x\n"
        "    assert acc == {claim}\n",
        "234",
        "444",
    ),
    # The callee has its own loop and its own assignments.
    "loop-calls-a-function-with-a-loop": (
        "    acc = 0\n"
        "    for i in (1, 2):\n"
        "        x = tri(i)\n"
        "        acc = acc * 100 + x\n"
        "    assert acc == {claim}\n",
        "612",
        "1212",
    ),
    # One callee, two call sites, each evaluated once per iteration.
    "one-function-two-call-sites-in-a-loop": (
        "    acc = 0\n"
        "    for i in (1, 2):\n"
        "        a = inc(i)\n"
        "        b = inc(i * 10)\n"
        "        acc = acc * 1000 + a * 100 + b\n"
        "    assert acc == {claim}\n",
        "211321",
        "321321",
    ),
}

# Programs whose value the lifter does not decide today.  Pinned as that, so a
# change that starts deciding them (or deciding them wrongly) shows here.
_UNDECIDED = {
    # The rebind sits under ``if i == 2`` inside the loop.
    "rebind-in-a-branch-in-a-loop": (
        "    acc = 0\n"
        "    for i in (1, 2, 3):\n"
        "        x = i\n"
        "        if i == 2:\n"
        "            x = x * 10\n"
        "        acc = acc * 100 + x\n"
        "    assert acc == {claim}\n",
        "12003",
        "12030",
        (1, 0),
    ),
    # Two levels of one function, an assignment at each.
    "recursion-two-levels": (
        "    r = down(1)\n    assert r == {claim}\n",
        "21",
        "22",
        (1, 2),
    ),
}


def _function(body: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree import nodes
    from sugar_source_tree.tree import SourceFile

    source = _HELPERS + "def test_it():\n" + body
    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, nodes.FunctionDef) and node.name == "test_it"
    )
    return source, function


def _faces(outcome) -> tuple[int, int]:
    """(completed faces, halted faces) of a function's universe outcome."""
    from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted

    if isinstance(outcome, Complete):
        return 1, 0
    assert isinstance(outcome, ExitSet), outcome
    return (
        sum(isinstance(face, Completed) for face in outcome.exits),
        sum(isinstance(face, Halted) for face in outcome.exits),
    )


# ---------------------------------------------------------------------------
# Values, at the reduction level.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(_PROGRAMS))
def test_the_truthful_claim_completes(name: str) -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    body, truthful, _lying = _PROGRAMS[name]
    _source, function = _function(body.format(claim=truthful))

    assert _faces(function_universe_outcome(function)) == (1, 0)


@pytest.mark.parametrize("name", sorted(_PROGRAMS))
def test_the_lying_claim_does_not_complete(name: str) -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    body, _truthful, lying = _PROGRAMS[name]
    _source, function = _function(body.format(claim=lying))

    completed, halted = _faces(function_universe_outcome(function))
    assert completed == 0
    assert halted >= 1


@pytest.mark.parametrize("name", sorted(_READ_INSIDE_THE_LOOP))
def test_a_claim_inside_the_loop_reads_each_iteration_s_own_values(name: str) -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    body, truthful, lying = _READ_INSIDE_THE_LOOP[name]

    _source, function = _function(body.format(claim=truthful))
    assert _faces(function_universe_outcome(function)) == (1, 0)

    _source, function = _function(body.format(claim=lying))
    completed, halted = _faces(function_universe_outcome(function))
    assert completed == 0
    assert halted >= 1


@pytest.mark.parametrize("name", sorted(_UNDECIDED))
def test_a_value_the_lifter_does_not_decide_today_has_the_same_faces_for_both_claims(
    name: str,
) -> None:
    """Not a twin: the truthful and the lying claim reduce alike, because the
    asserted value is not decided at the reduction.  Pinned so that a change to
    how assignments are recorded cannot start deciding it unnoticed."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    body, truthful, lying, faces = _UNDECIDED[name]
    for claim in (truthful, lying):
        _source, function = _function(body.format(claim=claim))
        assert _faces(function_universe_outcome(function)) == faces


# ---------------------------------------------------------------------------
# Values, through the real solver: truthful ``sat``, lying ``unsat``.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(_SOLVER_PROGRAMS))
def test_the_solver_holds_the_value_python_computes(name: str, tmp_path: Path) -> None:
    body, truthful, lying = _SOLVER_PROGRAMS[name]
    head = _HELPERS + "def test_it():\n"

    truthful_run = run_source_through_real_solver(
        tmp_path / "t", head + body.format(claim=truthful)
    )
    lying_run = run_source_through_real_solver(
        tmp_path / "l", head + body.format(claim=lying)
    )

    assert truthful_run.verdict == "sat"
    assert lying_run.verdict == "unsat"


# ---------------------------------------------------------------------------
# Applications of a callee body, counted on its ``return`` statement.
# ---------------------------------------------------------------------------


def _reductions_of(body: str, needle: str, monkeypatch) -> int:
    """How many times the ``return`` statement written as ``needle`` is reduced
    while the test function's universe is reduced: once per application of the
    callee that holds it."""
    from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    source, function = _function(body)
    start = source.index(needle)
    counts: Counter[str] = Counter()
    reduce_return = ReturnSugar.desugar

    def counted(self, ctx=None):
        span = getattr(self.site, "span", None)
        if span is not None and span.start == start:
            counts[needle] += 1
        return reduce_return(self, ctx)

    monkeypatch.setattr(ReturnSugar, "desugar", counted)
    function_universe_outcome(function)
    return counts[needle]


# name -> (program, the callee's return statement, calls Python makes,
#          applications measured today)
_APPLICATIONS = {
    "box-get": ("box-get", "return self.n + k", 1, 2),
    "box-get-read-twice": ("box-get-read-twice", "return self.n + k", 1, 3),
    "same-call-at-two-sites": ("same-call-at-two-sites", "return a + 1", 2, 4),
    "callee-twice-in-one-expression": (
        "callee-twice-in-one-expression",
        "return a + 1",
        2,
        4,
    ),
    "callee-of-callee": ("callee-of-callee", "return a + 1", 2, 4),
    "callee-with-a-local-assigned-twice": (
        "callee-with-a-local-assigned-twice",
        "return t * 2",
        2,
        4,
    ),
    "rebind": ("rebind", "return a + 1", 2, 5),
    "rebind-read-between": ("rebind-read-between", "return a + 1", 2, 10),
    "unrolled-loop-object": ("unrolled-loop-object", "return self.n + k", 2, 7),
}


@pytest.mark.parametrize("name", sorted(_APPLICATIONS))
def test_applications_of_a_callee_body_measured_today(name: str, monkeypatch) -> None:
    """Today's honest count, not a target: each read of an assigned name
    applies the callee again, because a right-hand side that is one plain
    completion is not recorded.  Python makes ``calls`` calls.

    The change expected to lower each number to ``calls`` is the one that makes
    an assignment evaluated once (plan row 7, map item 2: every right-hand side
    recorded under a key that tells two evaluations of one span apart, or a
    read that is a reference to the statement's evaluation).  When that lands
    these go red because the count dropped, and the numbers are lowered then.
    """
    program, needle, calls, measured = _APPLICATIONS[name]
    body, truthful, _lying = _PROGRAMS[program]

    applications = _reductions_of(body.format(claim=truthful), needle, monkeypatch)

    assert applications == measured
    assert applications > calls
