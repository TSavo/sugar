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
- The count tests that bounded how many times a callee's body is reduced
  (#7812) are gone with the application they measured: no call of a
  same-file function (step 5), class or method (step 6) applies a body.
- ``a = Box(1); a.get(3)``: the class call is its coordinate and edge
  (#7757 step 6), so ``a.get`` is a method of a call's result, whose
  dispatch is not decided at the reduction (dispatch at prove waits on the
  owner's ruling): the box programs are values the reduction does not
  decide (``_JOINED_AT_PROVE``), and open at prove (``_OPEN_UNTIL_DISPATCH``).
- Through the solver, a helper's own proof (no caller, so no actual) owes
  what it reads off a formal, and a source that owes anything is never
  ``sat`` as a whole (step 8): the truthful claim is read on the test
  function's own rows (``witness_harness.claim_verdict``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

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
    # The rebind sits under ``if i == 2`` inside the loop: ``i`` is the
    # item's own value, so the branch is decided on every item.
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
    ),
}

# A call of a same-file function is its coordinate and edge, joined at prove
# (#7757 step 5): the reduction never applies the callee's body, so the value
# of a program over such calls is not decided at the reduction.  Decided here
# before step 5, by following the body; each is now a value the reduction
# does not decide (``_UNDECIDED``'s test).  Through the solver the join
# decides the programs over such calls (``_SOLVER_PROGRAMS``): see
# ``test_the_solver_holds_the_value_python_computes``.
_JOINED_AT_PROVE = {
    name: _PROGRAMS.pop(name)
    for name in (
        "function-with-a-loop-called-twice",
        "callee-twice-in-one-expression",
        "callee-of-callee",
        "callee-with-a-local-applied-twice",
        "callee-with-a-local-assigned-twice",
        "same-call-at-two-sites",
        "rebind",
        "rebind-read-between",
        # A call of a same-file class is its coordinate and edge too (#7757
        # step 6): ``Box(1)`` builds no instance at the reduction, and a
        # method of the call's result is not dispatched there.
        "box-get",
        "box-get-read-twice",
        "unrolled-loop-object",
    )
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
    # Two levels of one function, an assignment at each.  The inner
    # ``down(n - 1)`` is a call of the function being applied, which the
    # reduction does not apply again: it is the unanswered call, so ``r`` is
    # not a decided value and neither claim about it is.
    "recursion-two-levels": (
        "    r = down(1)\n    assert r == {claim}\n",
        "21",
        "22",
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
    # A registration channel is seated at the door that opens the tree: a
    # loop body is rematerialized under construction testimony, and a call
    # there retains its source definition from this channel.
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
    return source, function


def _faces(outcome) -> tuple[int, int]:
    """(completed faces, halted faces) of a function's universe outcome."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

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


@pytest.mark.parametrize("name", sorted({**_UNDECIDED, **_JOINED_AT_PROVE}))
def test_a_value_the_lifter_does_not_decide_today_has_the_same_faces_for_both_claims(
    name: str,
) -> None:
    """Not a twin: the truthful and the lying claim reduce alike, because the
    asserted value is not decided at the reduction.  Pinned so that a change to
    how assignments are recorded cannot start deciding it unnoticed.

    Undecided is one completed face (the assert holding, under the guards of
    what is not decided) beside at least one halted face, the same for both
    claims.  A decided value would show as the truthful claim completing
    alone or the lying one not completing: either fails here.  How many
    halted faces stand beside the completion is each undecided operation's
    own business (the unanswered call's raise, an operation over its result,
    the assert's failure) and is not what this pins: it read two when this
    was written and three on main 17672f48f."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    body, truthful, lying = {**_UNDECIDED, **_JOINED_AT_PROVE}[name]
    seen = []
    for claim in (truthful, lying):
        _source, function = _function(body.format(claim=claim))
        completed, halted = _faces(function_universe_outcome(function))
        assert completed == 1
        assert halted >= 1
        seen.append((completed, halted))
    assert seen[0] == seen[1]


# ---------------------------------------------------------------------------
# Values, through the real solver: truthful ``sat``, lying ``unsat``.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(_SOLVER_PROGRAMS))
def test_the_solver_holds_the_value_python_computes(name: str, tmp_path: Path) -> None:
    """Decided at prove (#7757 steps 5 to 9): truthful ``sat``, lying
    ``unsat``.

    Each ``inc(i)`` / ``tri(i)`` is its coordinate and edge, joined at prove
    to the helper's contract (``out = binary_result(+, a, 1)`` under
    ``binary_op.completes(+, a, 1)`` for ``inc``), and completes where no
    halt the contract states holds (#8762).  The value is then read through
    the test function's own operations over the call results (``total + x``,
    ``acc * 10 + x``, ``a * 100 + b``): ``python:binary_result`` over
    ``python:call_result(call:test_witness.inc(i), ...)``.  The joined post's
    ``=`` states that result's builtin type and value, and the SMT emitter
    reads a binary operation's undecided operand at the type it is stated
    (``emitter::py_stated``, the guard ``py.eq`` already read), so the
    operation, its completes atom and the claim are decided over it.

    Measured ``open`` on the truthful half on main scorecards 43738710481
    (``38c87e62a``) and 43742056075 (``d6eb4f3ff``), pinned ``open`` by
    #8793 with the cause not identified.  The cause: the emitter decided
    ``python:binary_result`` only where both operands were syntactically
    decided (literals or decided operations), so ``0 + x`` over a joined
    call's result stayed the uninterpreted application whatever the post
    stated.  Before step 5 the reduction followed the callee's body and these
    were decided ``sat``/``unsat`` there."""
    body, truthful, lying = _SOLVER_PROGRAMS[name]
    head = _HELPERS + "def test_it():\n"

    truthful_run = run_source_through_real_solver(
        tmp_path / "t", head + body.format(claim=truthful)
    )
    lying_run = run_source_through_real_solver(
        tmp_path / "l", head + body.format(claim=lying)
    )

    # ``head`` ends with the test function's ``def`` line; every helper is
    # above it.
    test_line = head.count("\n")
    assert claim_verdict(truthful_run.prove_doc, claims_from_line=test_line) == "sat"
    assert lying_run.verdict == "unsat"


# Decided through the solver before #7757 step 6, by following ``Box``'s
# constructor and ``get``'s body at the reduction.  The class call is now its
# coordinate and edge, joined to ``python:test_witness.Box`` at prove; ``a.get``
# is a method of the call's result, whose dispatch is not decided at the
# reduction or at prove until the owner rules on dispatch at prove.  Open on
# both halves, never ``sat`` for the lie; listed on #7661.
_OPEN_UNTIL_DISPATCH = {
    "box-get": _JOINED_AT_PROVE["box-get"],
}


@pytest.mark.parametrize("name", sorted(_OPEN_UNTIL_DISPATCH))
def test_a_method_of_a_class_call_result_is_open_until_dispatch_at_prove(
    name: str, tmp_path: Path
) -> None:
    body, truthful, lying = _OPEN_UNTIL_DISPATCH[name]
    head = _HELPERS + "def test_it():\n"

    truthful_run = run_source_through_real_solver(
        tmp_path / "t", head + body.format(claim=truthful)
    )
    lying_run = run_source_through_real_solver(
        tmp_path / "l", head + body.format(claim=lying)
    )

    test_line = head.count("\n")
    assert claim_verdict(truthful_run.prove_doc, claims_from_line=test_line) != "sat"
    assert lying_run.verdict != "sat"
