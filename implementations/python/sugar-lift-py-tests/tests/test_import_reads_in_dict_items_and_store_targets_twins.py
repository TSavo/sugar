"""Solver twins: a function reading an import inside a dict display or a store
target is lifted, and the solver's answer is Python's (#7757).

Before, the lexical import pass never walked a Dict display's items, what a
store target reads, nor a ``def``'s evaluated annotations, so ``{"k":
idn.CONST}``, ``idn.TABLE["k"] = 1`` and ``def g(s: idn.T)`` reached
the meaning layer over the free name ``idn`` and ``ScopedFormula`` refused the
whole function, by name (``illegal free var(s): idn``).  Each read is now the
one two-faced undecided import read: the closed reference ``ref:<target>``
under its completes atom, an undetermined raise under the complement, the
``undecided`` member owed under the import's target symbol.

What the claims may say: the read is undecided (no proof of ``idn`` is
imported), so it is owed and nothing that rests on it is ``sat``; a claim the
read cannot change is still Python's.  A truthful claim is never ``unsat``; a
lying claim is never ``sat``.  The refusal is gone from the proof, and the
read's member is carried, never dropped.

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

# program -> (source with a ``{claim}`` hole, the read's target symbol)
_PROGRAMS = {
    "dict-value": (
        "import idn\n\n\n"
        "def test_f():\n"
        "    d = {'k': idn.CONST, 'n': 1}\n"
        "    assert d['n'] == {claim}\n",
        "python:idn.CONST",
    ),
    "dict-key": (
        "import idn\n\n\n"
        "def test_f():\n"
        "    d = {idn.KEY: 0, 'n': 1}\n"
        "    assert d['n'] == {claim}\n",
        "python:idn.KEY",
    ),
    "subscript-store-receiver": (
        "import idn\n\n\n"
        "def test_f():\n"
        "    idn.TABLE['k'] = 1\n"
        "    n = 1\n"
        "    assert n == {claim}\n",
        "python:idn.TABLE",
    ),
    "subscript-delete-receiver": (
        "import idn\n\n\n"
        "def test_f():\n"
        "    del idn.TABLE['k']\n"
        "    n = 1\n"
        "    assert n == {claim}\n",
        "python:idn.TABLE",
    ),
    "evaluated-annotation": (
        "import idn\n\n\n"
        "def test_f():\n"
        "    def g(s: idn.T):\n"
        "        return s\n"
        "    n = 1\n"
        "    assert n == {claim}\n",
        "python:idn.T",
    ),
}
_HALVES = {"truthful": 1, "lying": 2}


def _members(lift_doc: dict) -> list[dict]:
    """Every ``undecided`` row, as the kit sent it to mint."""
    return [row for row in lift_doc["ir"] if row.get("kind") == "undecided"]


@pytest.mark.parametrize("program", sorted(_PROGRAMS))
def test_an_import_read_in_a_dict_or_store_target_is_lifted_and_honest(
    tmp_path: Path, program: str
) -> None:
    source, symbol = _PROGRAMS[program]
    for half, claim in _HALVES.items():
        project = tmp_path / half
        result = run_source_through_real_solver(
            project, source.replace("{claim}", str(claim))
        )
        (proof,) = tuple(project.glob("*.proof"))
        assert _DELETED_REFUSAL not in proof.read_bytes(), (program, half)
        # The read is carried: its member is owed under the import's symbol.
        assert any(
            member.get("symbol") == symbol for member in _members(result.lift_doc)
        ), (program, half, _members(result.lift_doc))
        verdict = prove_verdict(result.prove_doc)
        if half == "truthful":
            assert verdict != "unsat", (program, result.prove_doc)
        else:
            assert verdict != "sat", (program, result.prove_doc)
