"""Twins: ``f(*xs)`` reads ``*`` through the one ``*`` reader (#7757 S3).

``SpreadCallSugar._finish`` had its own ``*`` reader: for a class, a
function value or a bound method it took a ``*`` operand only when it was a
``TupleValue`` -- any tuple, one holding a container a call may have changed
among them -- and refused every other operand by name (``SugarNotWritten``),
so ``C(*args)`` with ``args`` a list refused the whole function.  The
``[*xs]`` display reads ``*`` through ``_spread_members``: a ``list`` or
``tuple`` whose contents are current.

The call now reads ``*`` through that one reader
(``spread_sugar._call_positional``).  A current list or tuple binds its
members in order; any other operand -- a call's result, a container a call
may have changed -- gives no exact positional roster, and the call is the
one unanswered call (``UnknownCalleeCallV1``), two-faced and owed, exactly
as a ``**`` operand with no keyword roster is (#9053).

The decided shape reads ``sat`` and its lie ``unsat``.  For every shape a
lying claim is never ``sat`` and a truthful one never ``unsat``.  Each half
goes through ``run_source_through_real_solver``: real ``sugar mint`` then
real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

# ``name: (source, truthful claim, lying claim, decided)``.  Braces are
# doubled: the source is a ``str.format`` template.  The claim is stated in
# the test's own body, over locals: a same-file call is a coordinate joined
# at prove, so only the shapes that are owed go through one.
_SHAPES = {
    # A list this frame made, spread into a local lambda: its members bind
    # ``a = 1, b = 2`` in order, as ``f(*(1, 2))`` does.
    "current-list-to-lambda": (
        "def test_a():\n"
        "    xs = [1, 2]\n"
        "    f = lambda a, b: a - b\n"
        "    assert {claim}\n",
        "f(*xs) == -1",
        "f(*xs) == 1",
        True,
    ),
    # The audit's shape: ``C(*args)`` with ``args`` a list.  It refused the
    # function; it now binds the constructor's formals from the members.
    "current-list-to-class": (
        "class C:\n"
        "    def __init__(self, a, b):\n"
        "        self.b = b\n"
        "\n"
        "\n"
        "def test_a():\n"
        "    args = [1, 2]\n"
        "    c = C(*args)\n"
        "    assert {claim}\n",
        "c.b == 2",
        "c.b == 1",
        False,
    ),
    # A same-file call's result: its members are not held here, so the
    # spread call has no exact roster and is owed.
    "call-result-is-owed": (
        "def g():\n"
        "    return [1, 2]\n"
        "\n"
        "\n"
        "def test_a():\n"
        "    f = lambda a, b: a - b\n"
        "    assert {claim}\n",
        "f(*g()) == -1",
        "f(*g()) == 1",
        False,
    ),
    # A list this frame made, then handed to a call that changes it: the
    # members the frame made are not its contents after the call.  Python
    # binds ``a = 5``; the old members say ``a = 1``.
    "list-changed-by-callee-is-owed": (
        "def bump(xs):\n"
        "    xs[0] = 5\n"
        "\n"
        "\n"
        "def test_a():\n"
        "    xs = [1, 2]\n"
        "    bump(xs)\n"
        "    f = lambda a, b: a - b\n"
        "    assert {claim}\n",
        "f(*xs) == 3",
        "f(*xs) == -1",
        False,
    ),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows the helpers."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_star_spread_never_refutes_a_truth_nor_admits_a_lie(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, truthful, lying, decided = _SHAPES[shape]
    text = source.format(claim=truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
        if decided:
            assert verdict == "unsat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
        if decided:
            assert verdict == "sat", result.prove_doc
