"""Solver twins: an import read in an evaluated annotated-assignment
annotation is lifted, and the solver's answer is Python's (#7757).

``class C: v: idn.T`` (numpy ``class UniqueAllResult(NamedTuple): values:
np.ndarray``) and a module-level ``x: idn.T = 1`` evaluate their annotation
when the statement runs.  The lexical import pass never walked it, so the
read reached the meaning layer over the free name ``idn`` and
``ScopedFormula`` refused, by name (``illegal free var(s): idn``).  Each read
is now the one two-faced undecided import read: the closed reference under
its completes atom, an undetermined raise under the complement, the
``undecided`` member owed under the import's target symbol.

What the claims may say: the read is undecided (no proof of ``idn`` is
imported), so nothing that rests on it is ``sat``; a truthful claim is never
``unsat`` and a lying claim is never ``sat``.  The refusal is gone from the
proof.

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

# program -> (source with a ``{claim}`` hole, the symbol whose member the
# test's own universe carries, or None where the read is the module's run)
_PROGRAMS = {
    "local-class-body": (
        "import idn\n\n\n"
        "def test_f():\n"
        "    class Row:\n"
        "        v: idn.T\n"
        "    n = 1\n"
        "    assert n == {claim}\n",
        "python:idn.T",
    ),
    "module-class-body": (
        "import idn\n\n\n"
        "class Row:\n"
        "    v: idn.T\n\n\n"
        "def test_f():\n"
        "    k = Row\n"
        "    n = 1\n"
        "    assert n == {claim}\n",
        None,
    ),
    "module-annotated-name": (
        "import idn\n\n"
        "x: idn.T = 1\n\n\n"
        "def test_f():\n"
        "    n = 1\n"
        "    assert n == {claim}\n",
        None,
    ),
}
_HALVES = {"truthful": 1, "lying": 2}


def _members(lift_doc: dict) -> list[dict]:
    """Every ``undecided`` row, as the kit sent it to mint."""
    return [row for row in lift_doc["ir"] if row.get("kind") == "undecided"]


@pytest.mark.parametrize("program", sorted(_PROGRAMS))
def test_an_import_read_in_an_annotation_is_lifted_and_honest(
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
        if symbol is not None:
            # The read is carried: its member is owed under the import's
            # symbol, never dropped.
            assert any(
                member.get("symbol") == symbol for member in _members(result.lift_doc)
            ), (program, half, _members(result.lift_doc))
        verdict = prove_verdict(result.prove_doc)
        if half == "truthful":
            assert verdict != "unsat", (program, result.prove_doc)
        else:
            assert verdict != "sat", (program, result.prove_doc)
