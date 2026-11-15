"""`sugar mint` and the board's door read different content for the same file (#7796).

Plan row 5 (the board reads the one lift). Measured on main at ``af341f3cd``
with a 16-line module: a same-module context manager class, a function that
enters it, and a test function.

When measured, ``sugar mint`` refused the ``with`` while the board's door
built it from a table a population pre-pass seated at file open.  That
pre-pass is deleted (#7757): no door reads a callee body before construction,
and the ``with``'s manager is what its head reduces to, the same in every
door.

The twin below states what the module's proof should say; it is a plain test,
not skipped and not marked.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

_MODULE = (
    "class Resource:\n"
    "    def __init__(self, target):\n"
    "        self.target = target\n"
    "    def __enter__(self):\n"
    "        return self.target\n"
    "    def __exit__(self, *exc):\n"
    "        pass\n"
    "\n"
    "\n"
    "def f():\n"
    "    with Resource(1) as value:\n"
    "        return value\n"
    "\n"
    "\n"
    "def test_f():\n"
    "    assert f() == {claim}\n"
)


def test_a_with_over_a_same_module_manager_reaches_the_solver(tmp_path: Path) -> None:
    """``f()`` enters ``Resource(1)`` and returns 1.

    Before #7757 step 6 the manager was made in ``f``'s frame and
    ``__init__`` and ``__enter__`` were applied to it, so ``f()`` was 1 at
    the reduction: truthful ``sat``, lying ``unsat``.  Since step 6 neither
    body is applied (below).

    ``Resource.__init__``'s and ``__enter__``'s OWN proofs have no caller:
    ``self.target = target`` and ``return self.target`` act on a formal with
    no actual, and each owes an ``undecided`` member (step 8).  A source that
    owes anything is never ``sat`` as a whole, so the truthful half is read on
    the test function's own claims (``witness_harness.claim_verdict``): what
    the methods' own proofs owe sits above the test function and is set aside.
    """
    truthful = run_source_through_real_solver(tmp_path / "t", _MODULE.format(claim=1))
    lying = run_source_through_real_solver(tmp_path / "l", _MODULE.format(claim=2))
    (test_line,) = (
        number
        for number, line in enumerate(_MODULE.splitlines(), start=1)
        if line.startswith("def test_")
    )
    # Since #7757 step 6 (#8738, #8744) ``Resource(1)`` is an edge and
    # ``__enter__`` on its result is a method call on a call's result, whose
    # dispatch is not decided at the reduction: the unanswered call.  ``f()``
    # returns that call's value, which nothing states, so the truthful claim
    # reads ``open`` on main (scorecard 43738710481), listed on #7661.
    # Dispatch at prove (#7757 step 8: #8750 prove side, the lift side not
    # merged) decides it: truthful ``sat``, lying ``unsat``.  Until then the
    # lie reads ``open`` by the same undecided value, never ``sat``.
    assert claim_verdict(truthful.prove_doc, claims_from_line=test_line) == "open"
    assert lying.verdict == "open"
