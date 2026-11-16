"""Twins: a unary operator on a call's result is the one undecided unary
(#7757, audit 4 row NEW-8).

``-f()`` / ``~f()`` were once refused by name (the operand's type is
undecided), while ``+f()`` only halted: an outcome with
no completed face, so a truthful ``assert +f() == 3`` reached only through it
could be stated as refuted.  A call's result is an operand whose type
nothing here decides, as a formal's is, so each is the one undecided unary
(``FloorValue.undecided_unary``): it completes with
``python:unary_result("<op>", call:f(), <key>)`` under its completes atom,
halts undetermined under the complement, and owes the operation.  The
claim over it is never decided by a fold the lift did not make.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each
half goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

_HELPER = "def f():\n" "    return 3\n" "\n" "\n"

# ``name: (operator, truthful claim, lying claim)``.
_SHAPES = {
    "plus": ("+f()", "+f() == 3", "+f() == 4"),
    "minus": ("-f()", "-f() == -3", "-f() == 3"),
    "invert": ("~f()", "~f() == -4", "~f() == 4"),
}


def _source(claim: str) -> str:
    return _HELPER + "def test_unary():\n" f"    assert {claim}\n"


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows the helper."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_unary_on_a_call_result_never_refutes_a_truth_nor_admits_a_lie(
    tmp_path: Path, shape: str, half: str
) -> None:
    _operation, truthful, lying = _SHAPES[shape]
    text = _source(truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
