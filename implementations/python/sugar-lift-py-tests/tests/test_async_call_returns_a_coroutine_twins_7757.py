"""Twins: an ``async def``'s call returns a coroutine and runs none of its
body; an ``await`` is the one undecided read (#7757 step 6).

An ``async def`` with no ``yield`` stated its body's ``return`` as the
call's ``out``, and its body's halts as the call's panic loci.  Python's
call of a coroutine function runs none of the body: it returns a fresh
coroutine object, and the body runs (and returns, and raises) only where
the coroutine is awaited.  So ``async def f(): return 9`` with ``assert
f() == 9`` could read ``sat``: a lie.

Now the coroutine function's contract is the generator function's
(``UniverseValue.suspends``, ``tree_enumerate.reduction_rows``, #9175): it
states nothing of the call's ``out`` and none of the body's halts as the
call's.  The body's own claims are decided as any body's are.  An
``await`` (``AwaitSugar``) evaluates its operand, its halts kept, then is
the one two-faced undecided operation: it completes with
``python:await_result(<key>)`` under ``python:await_op.completes`` and
halts undetermined under the complement, owed either way.  No coroutine's
contract states what awaiting it gives, so nothing is joined there.

Shapes:

- ``call-is-not-its-return``: ``f() == 9`` where the body returns ``9``:
  the call is the coroutine, so the lie is never ``sat``.
- ``call-never-halts``: a body that certainly raises; ``f()`` itself never
  raises, so the handler never runs: decided at prove, where the contract
  states no halt of the call.
- ``after-an-await``: an ``assert`` after ``r = await c`` is the body's
  claim, decided on the await's completed face.
- ``await-operand-halts``: the operand ``1 // 0`` raises before anything is
  awaited; its halt is kept and the handler runs: decided.
- ``await-result-is-undecided``: ``await nine()`` where ``nine``'s body
  returns ``9``: what the await gives is the undecided read, so neither
  claim over it is decided.

Each half goes through ``run_source_through_real_solver``: real ``sugar
mint`` then real ``sugar prove``.  Neither half's lift names the old
refusal (``Await.sugar``).  A lying claim is ``unsat`` where the shape
decides it and never ``sat`` anywhere; a truthful one is never ``unsat``.
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
    "call-is-not-its-return": (
        "async def f():\n    return 9\n",
        "assert f() {claim} 9\n",
        "!=",
        "==",
        False,
    ),
    "call-never-halts": (
        "async def f():\n    raise ValueError('x')\n",
        "try:\n"
        "    f()\n"
        "    raised = 0\n"
        "except ValueError:\n"
        "    raised = 1\n"
        "assert raised == {claim}\n",
        "0",
        "1",
        True,
    ),
    "after-an-await": (
        "async def g(c):\n"
        "    r = await c\n"
        "    total = 1 + 1\n"
        "    assert total == {claim}\n",
        "pass\n",
        "2",
        "3",
        True,
    ),
    "await-operand-halts": (
        "async def g():\n"
        "    ok = 0\n"
        "    try:\n"
        "        await (1 // 0)\n"
        "    except ZeroDivisionError:\n"
        "        ok = 1\n"
        "    assert ok == {claim}\n",
        "pass\n",
        "1",
        "0",
        True,
    ),
    "await-result-is-undecided": (
        "async def nine():\n"
        "    return 9\n"
        "\n\n"
        "async def g():\n"
        "    x = await nine()\n"
        "    assert x == {claim}\n",
        "pass\n",
        "9",
        "8",
        False,
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
def test_an_async_call_returns_a_coroutine(
    tmp_path: Path, shape: str, half: str
) -> None:
    helpers, body, truthful, lying, lie_decided = _SHAPES[shape]
    source, test_line = _source(
        helpers, body, truthful if half == "truthful" else lying
    )
    result = run_source_through_real_solver(tmp_path / shape / half, source)
    # No await refuses the function it is in.
    assert "Await.sugar" not in json.dumps(result.lift_doc), result.lift_doc
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
