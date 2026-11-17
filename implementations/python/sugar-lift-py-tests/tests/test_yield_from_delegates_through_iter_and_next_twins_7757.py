"""Twins: a ``yield from`` delegates through the one ``iter`` and ``next``
operations, and what it hands back is the one undecided read (#7757 step
6).

A ``yield from`` refused its whole function by name (owner
``YieldFromSugar.desugar``, "yield from suspension reached eager expression
reduction"): 11 pandas and 11 numpy functions on the 13e3413ad lane
(``pandas.core.common.flatten``, ``BaseGrouper.get_iterator``, the numpy
``_dispatcher`` helpers that ``yield from`` their operands).

Now a ``yield from`` is one operation of the one body reduction
(``YieldFromSugar``): its operand is evaluated (its halts kept), then
``iter`` of it is the one ``iter`` operation (``iterated``), a step of the
sub-iterator the one ``next`` operation (``stepped``), and what the
delegation hands back is the two-faced undecided resume a ``yield``'s is
(``suspension_resumed``): it completes with
``python:yield_from_result(<key>)`` under ``python:yield_from_op.completes``
and halts undetermined under the complement, both faces owing the
``undecided`` member.  The generator function's call runs none of the body
(``UniverseValue.suspends``, #9175).

Shapes:

- ``after-a-yield-from``: an ``assert`` after ``r = yield from xs`` (a
  formal: ``iter`` and ``next`` undecided) is the body's claim, decided.
- ``yield-from-a-tuple``: the iteration is decided never to raise, so no
  ``iter`` or ``next`` is submitted; the claim after it is decided.
- ``operand-halts``: ``yield from (1 // 0)`` raises before anything is
  delegated; its halt is kept and the handler runs: decided.
- ``result-is-undecided``: ``r = yield from sub()`` where ``sub`` returns
  ``7``: what the delegation hands back is the undecided read (and
  ``sub()`` is a generator, not its return), so neither claim over ``r`` is
  decided.
- ``call-never-halts``: a body whose ``yield from`` operand certainly
  raises; ``gen()`` itself never raises, so the handler never runs: decided
  at prove, where the contract states no halt of the call.

Each half goes through ``run_source_through_real_solver``: real ``sugar
mint`` then real ``sugar prove``.  Neither half's lift names the old
refusal (``YieldFromSugar.desugar``).  A lying claim is ``unsat`` where the shape decides it
and never ``sat`` anywhere; a truthful one is never ``unsat``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

# ``name: (helpers, body, truthful, lying, lie decided)``: ``helpers`` run
# before ``test_f``; ``truthful``/``lying`` replace ``{claim}`` in the
# helpers and in ``test_f``'s body.  ``lie decided``: the lying half is
# ``unsat``, not only never ``sat``.
_SHAPES = {
    "after-a-yield-from": (
        "def gen(xs):\n"
        "    r = yield from xs\n"
        "    total = 1 + 1\n"
        "    assert total == {claim}\n",
        "pass\n",
        "2",
        "3",
        True,
    ),
    "yield-from-a-tuple": (
        "def gen():\n"
        "    yield from (1, 2)\n"
        "    total = 4\n"
        "    assert total == {claim}\n",
        "pass\n",
        "4",
        "5",
        True,
    ),
    "operand-halts": (
        "def gen():\n"
        "    ok = 0\n"
        "    try:\n"
        "        yield from (1 // 0)\n"
        "    except ZeroDivisionError:\n"
        "        ok = 1\n"
        "    assert ok == {claim}\n",
        "pass\n",
        "1",
        "0",
        True,
    ),
    "result-is-undecided": (
        "def sub():\n"
        "    yield 1\n"
        "    return 7\n"
        "\n\n"
        "def gen():\n"
        "    r = yield from sub()\n"
        "    assert r == {claim}\n",
        "pass\n",
        "7",
        "8",
        False,
    ),
    "call-never-halts": (
        "def gen():\n    yield from (1 // 0)\n",
        "try:\n"
        "    gen()\n"
        "    raised = 0\n"
        "except ZeroDivisionError:\n"
        "    raised = 1\n"
        "assert raised == {claim}\n",
        "0",
        "1",
        True,
    ),
}


def _source(helpers: str, body: str, claim: str) -> tuple[str, int]:
    """The source, and the line of ``def test_f():`` (its claims start
    there, after every helper)."""
    prefix = helpers.replace("{claim}", claim) + "\n\n"
    lines = "".join(
        f"    {line}\n" for line in body.replace("{claim}", claim).splitlines()
    )
    return prefix + "def test_f():\n" + lines, prefix.count("\n") + 1


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_yield_from_delegates_through_iter_and_next(
    tmp_path: Path, shape: str, half: str
) -> None:
    helpers, body, truthful, lying, lie_decided = _SHAPES[shape]
    source, test_line = _source(
        helpers, body, truthful if half == "truthful" else lying
    )
    result = run_source_through_real_solver(tmp_path / shape / half, source)
    # No yield from refuses the function it is in.
    assert "YieldFromSugar.desugar" not in json.dumps(result.lift_doc), result.lift_doc
    verdict = claim_verdict(
        result.prove_doc, claims_from_line=test_line, lift_doc=result.lift_doc
    )
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
        if lie_decided:
            assert verdict == "unsat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
