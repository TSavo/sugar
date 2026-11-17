"""Twins: a generator function's body is reduced through its ``yield``s, and
its contract states no result and no halt of its call (#7757 step 6).

A ``yield`` refused the whole function by name (owner
``YieldSuspensionSugar.desugar``, "yield suspension reached eager expression
reduction"): 74 pandas and 24 numpy functions on the 13e3413ad lane, every
``@contextmanager`` (``try: yield / finally:``), every pytest fixture that
yields, every ``__iter__`` that loops and yields.

Now a ``yield`` is one operation of the one body reduction: its operand is
evaluated (its halts kept), then the resume is the two-faced undecided
operation (``YieldSuspensionSugar._resumed``): it completes with
``python:yield_result(<key>)`` under ``python:yield_op.completes`` and halts
with an undetermined raise (``throw``/``close`` at the ``yield``) under the
complement, both faces owing the ``undecided`` member.  The body's own
claims after the ``yield`` are decided as any body's are.

The call of a generator function runs none of the body and returns the
generator.  So its universe states nothing of the call's ``out``
(``UniverseValue.suspends``) -- never the value the body ``return``s,
which is ``StopIteration``'s -- and its contract states none of the body's
halts as the call's panic loci (``tree_enumerate.reduction_rows``): a halt
of the body is taken where the generator is resumed, by a consumer whose
``next`` is the one undecided read.

Shapes:

- ``after-a-yield``: an ``assert`` after ``x = yield 1`` is the body's claim,
  decided.
- ``try-yield-finally``: the ``@contextmanager`` shape; the ``finally`` runs
  on the resume's completed face and its claim after it is decided.
- ``yield-in-a-loop``: the ``__iter__`` shape, ``for x in xs: yield x``; the
  claim after the loop is decided.
- ``call-is-not-its-return``: ``gen() == 9`` where the body returns ``9``:
  the call is the generator, so the lie is never ``sat``.
- ``call-never-halts``: a body that certainly raises before its ``yield``;
  ``gen()`` itself never raises, so the handler never runs: decided at
  prove, where the contract states no halt of the call.

Each half goes through ``run_source_through_real_solver``: real ``sugar
mint`` then real ``sugar prove``.  Neither half's lift names
``YieldSuspensionSugar``.  A lying claim is ``unsat`` where the shape
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

# ``name: (helpers, truthful, lying, lie decided)``: ``helpers`` run before
# ``test_f``; ``truthful``/``lying`` replace ``{claim}`` in the helpers and
# in ``test_f``'s body.  ``lie decided``: the lying half is ``unsat``, not
# only never ``sat``.
_SHAPES = {
    "after-a-yield": (
        "def gen():\n"
        "    sent = yield 1\n"
        "    total = 1 + 1\n"
        "    assert total == {claim}\n",
        "pass\n",
        "2",
        "3",
        True,
    ),
    "try-yield-finally": (
        "def gen(flag):\n"
        "    before = 1\n"
        "    try:\n"
        "        yield before\n"
        "    finally:\n"
        "        after = 2\n"
        "    assert after == {claim}\n",
        "pass\n",
        "2",
        "3",
        True,
    ),
    "yield-in-a-loop": (
        "def gen(xs):\n"
        "    for x in xs:\n"
        "        yield x\n"
        "    total = 4\n"
        "    assert total == {claim}\n",
        "pass\n",
        "4",
        "5",
        True,
    ),
    "call-is-not-its-return": (
        "def gen():\n    yield 1\n    return 9\n",
        "assert gen() {claim} 9\n",
        "!=",
        "==",
        False,
    ),
    "call-never-halts": (
        "def gen():\n    raise ValueError('x')\n    yield 1\n",
        "try:\n"
        "    gen()\n"
        "    raised = 0\n"
        "except ValueError:\n"
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
def test_a_generator_body_reduces_through_its_yields(
    tmp_path: Path, shape: str, half: str
) -> None:
    helpers, body, truthful, lying, lie_decided = _SHAPES[shape]
    source, test_line = _source(
        helpers, body, truthful if half == "truthful" else lying
    )
    result = run_source_through_real_solver(tmp_path / shape / half, source)
    # No yield refuses the function it is in.
    assert "YieldSuspensionSugar" not in json.dumps(result.lift_doc), result.lift_doc
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
