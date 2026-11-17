"""Solver twins: a caller of a class, or of a ``def`` bound on one route of
a module ``if``, takes the ``global:`` inputs that call's edge supplies, and
the solver's answer is Python's (#7757 step 5).

Before, the caller's contract took only a module ``def``'s inputs, so the
edge to the constructor ``def`` (``Box()``) or to the route's ``def``
(``helper()`` under ``if idn.FLAG:``) supplied a variable no contract binds,
and ``ScopedFormula`` refused the caller by it (``illegal free var(s):
undecided:global:<name>@...``).  The read of the global is now the caller's
own ``global:`` input, supplied by its own caller in turn.

A truthful claim is never ``unsat`` and a lying claim is never ``sat``; the
refusal is gone from the proof.  Each twin goes through
``run_source_through_real_solver``: real ``sugar mint`` then real ``sugar
prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    prove_verdict,
    run_source_through_real_solver,
)

_DELETED_REFUSAL = b"illegal free var"

_PROGRAMS = {
    "class-call": (
        "X = 1\n\n\n"
        "class Box:\n"
        "    def __init__(self):\n"
        "        self.v = X\n\n\n"
        "def make():\n"
        "    return Box()\n\n\n"
        "def test_f():\n"
        "    b = make()\n"
        "    n = 1\n"
        "    assert n == {claim}\n"
    ),
    "def-on-one-route": (
        "import idn\n\n"
        "LIMIT = 3\n\n"
        "if idn.FLAG:\n\n"
        "    def helper():\n"
        "        return LIMIT\n\n\n"
        "def caller():\n"
        "    return helper()\n\n\n"
        "def test_f():\n"
        "    n = 1\n"
        "    assert n == {claim}\n"
    ),
    "lambda-on-one-route": (
        "import idn\n\n"
        "LIMIT = 3\n\n"
        "if idn.FLAG:\n\n"
        "    def helper(x):\n"
        "        return x + LIMIT\n\n"
        "    OPS = {'add': lambda x: helper(x)}\n\n\n"
        "def test_f():\n"
        "    n = 1\n"
        "    assert n == {claim}\n"
    ),
}
_HALVES = {"truthful": 1, "lying": 2}


@pytest.mark.parametrize("program", sorted(_PROGRAMS))
def test_a_call_joined_definition_s_globals_are_the_caller_s_inputs(
    tmp_path: Path, program: str
) -> None:
    source = _PROGRAMS[program]
    for half, claim in _HALVES.items():
        project = tmp_path / half
        result = run_source_through_real_solver(
            project, source.replace("{claim}", str(claim))
        )
        (proof,) = tuple(project.glob("*.proof"))
        assert _DELETED_REFUSAL not in proof.read_bytes(), (program, half)
        verdict = prove_verdict(result.prove_doc)
        if half == "truthful":
            assert verdict != "unsat", (program, result.prove_doc)
        else:
            assert verdict != "sat", (program, result.prove_doc)
