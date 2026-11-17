"""Solver twins: a builtin's name a star import may rebind, read as a value,
is lifted as the function's undecided ``global:`` input, and the solver's
answer is Python's (#7757, carry undecided).

``isinstance(keys, tuple)`` and ``return NotImplemented`` under ``from m
import *`` were the free names ``tuple`` and ``NotImplemented``, and
``ScopedFormula`` refused the function by them.  The read is now the input
with no stated value: what the star import bound, or the builtin, which the
lifter does not decide.  A claim that rests on it is not decided either way.

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
    "isinstance-tuple": (
        "from idn import *\n\n\n"
        "def lexsort(keys):\n"
        "    if isinstance(keys, tuple):\n"
        "        return keys\n"
        "    return (keys,)\n\n\n"
        "def test_f():\n"
        "    n = 1\n"
        "    assert n == {claim}\n"
    ),
    "return-not-implemented": (
        "from idn import *\n\n\n"
        "def rmod(other):\n"
        "    return NotImplemented\n\n\n"
        "def test_f():\n"
        "    n = 1\n"
        "    assert n == {claim}\n"
    ),
    "claim-reads-the-builtin": (
        "from idn import *\n\n\n"
        "def kind():\n"
        "    return dict\n\n\n"
        "def test_f():\n"
        "    k = kind()\n"
        "    assert (k is dict) == {claim}\n"
    ),
}
_HALVES = {"truthful": "True", "lying": "False"}
_PLAIN_HALVES = {"truthful": "1", "lying": "2"}


@pytest.mark.parametrize("program", sorted(_PROGRAMS))
def test_a_star_import_builtin_value_read_is_lifted_and_honest(
    tmp_path: Path, program: str
) -> None:
    source = _PROGRAMS[program]
    halves = _HALVES if program == "claim-reads-the-builtin" else _PLAIN_HALVES
    for half, claim in halves.items():
        project = tmp_path / half
        result = run_source_through_real_solver(
            project, source.replace("{claim}", claim)
        )
        (proof,) = tuple(project.glob("*.proof"))
        assert _DELETED_REFUSAL not in proof.read_bytes(), (program, half)
        verdict = prove_verdict(result.prove_doc)
        if half == "truthful":
            assert verdict != "unsat", (program, result.prove_doc)
        else:
            assert verdict != "sat", (program, result.prove_doc)
