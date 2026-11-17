"""Solver twins: a function reading a module alias as a value is lifted (#7757).

``import operator`` then ``getattr(operator, name)``: the read of ``operator``
is no import member, and it was the free name, so ``ScopedFormula`` refused
the whole function by it (``illegal free var(s): operator``; ~20 pandas
functions: ``getattr(np, method)``, ``hasattr(pd, "get_option")``,
``m.setattr(locale, ...)``).  The read is now the module the import bound,
the closed coordinate ``python:module(<module>)``: the read runs nothing, so
it is the one completed arm.  What is done with the module stays that
operation's own undecided read (``getattr`` of a name the lifter holds no
namespace for).

A truthful claim is never ``unsat``; a lying claim is never ``sat``.  Where
nothing is owed (``m = idn`` only binds the module) the claim is decided:
``sat`` for the truth, ``unsat`` for the lie.

Each twin goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    prove_verdict,
    run_source_through_real_solver,
)

_DELETED_REFUSAL = b"illegal free var"

# program -> (source with a ``{claim}`` hole, whether nothing is owed)
_PROGRAMS = {
    "bind-the-module": (
        "import idn\n\n\n"
        "def test_f():\n"
        "    m = idn\n"
        "    n = 1\n"
        "    assert n == {claim}\n",
        True,
    ),
    "getattr-on-the-module": (
        "import idn\n\n\n"
        "def test_f():\n"
        "    op = getattr(idn, 'add')\n"
        "    n = 1\n"
        "    assert n == {claim}\n",
        False,
    ),
    "aliased-module-in-a-call": (
        "import idn as q\n\n\n"
        "def test_f():\n"
        "    ok = hasattr(q, 'add')\n"
        "    n = 1\n"
        "    assert n == {claim}\n",
        False,
    ),
}
_HALVES = {"truthful": 1, "lying": 2}


@pytest.mark.parametrize("program", sorted(_PROGRAMS))
def test_a_module_alias_read_is_lifted_and_honest(
    tmp_path: Path, program: str
) -> None:
    source, decided = _PROGRAMS[program]
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
            if decided:
                assert verdict == "sat", (program, result.prove_doc)
        else:
            assert verdict != "sat", (program, result.prove_doc)
            if decided:
                assert verdict == "unsat", (program, result.prove_doc)
