"""Solver twins: a class body's read of a name an earlier ``def`` in that
body binds is lifted, and the solver's answer is Python's (#7757).

``@size.setter``, ``size = property(_get, _set)``, ``getT = T.fget`` and
``c = coeffs`` each read the name the class body's ``def`` above them bound.
That ``def`` bound nothing for the statements after it, so the read stayed
the bare name and ``ScopedFormula`` refused the class, and every method of
it, by the free name (``illegal free var(s): mgr_locs``, ``_get_names,
_set_names``, ``coeffs``, ``flat``, ``A, A1, H, I, T``; about 76 pandas and
57 numpy functions on the nine-step lane at main 13e3413ad).  The read is
now the value the statement bound under its evaluation key, as Python's
class body finds it in its own namespace (``LOAD_NAME``).

What the claims may say: a truthful claim is never ``unsat`` and a lying
claim is never ``sat``.  The refusal is gone from the proof.

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

# program -> source with a ``{claim}`` hole
_PROGRAMS = {
    "property-setter": (
        "class Box:\n"
        "    @property\n"
        "    def size(self):\n"
        "        return 1\n\n"
        "    @size.setter\n"
        "    def size(self, value):\n"
        "        pass\n\n\n"
        "def test_f():\n"
        "    k = Box\n"
        "    n = 1\n"
        "    assert n == {claim}\n"
    ),
    "property-of-plain-methods": (
        "class Box:\n"
        "    def _get(self):\n"
        "        return 1\n\n"
        "    def _set(self, value):\n"
        "        pass\n\n"
        "    size = property(fset=_set, fget=_get)\n\n\n"
        "def test_f():\n"
        "    k = Box\n"
        "    n = 1\n"
        "    assert n == {claim}\n"
    ),
    "getter-of-a-property": (
        "class Box:\n"
        "    @property\n"
        "    def T(self):\n"
        "        return 1\n\n"
        "    getT = T.fget\n\n\n"
        "def test_f():\n"
        "    k = Box\n"
        "    n = 1\n"
        "    assert n == {claim}\n"
    ),
    "alias-of-a-method": (
        "class Box:\n"
        "    def coeffs(self):\n"
        "        return 1\n\n"
        "    c = coef = coeffs\n\n\n"
        "def test_f():\n"
        "    k = Box\n"
        "    n = 1\n"
        "    assert n == {claim}\n"
    ),
    "read-through-the-property": (
        "class Box:\n"
        "    def _get(self):\n"
        "        return 1\n\n"
        "    size = property(_get)\n\n\n"
        "def test_f():\n"
        "    assert Box().size == {claim}\n"
    ),
}
_HALVES = {"truthful": 1, "lying": 2}


@pytest.mark.parametrize("program", sorted(_PROGRAMS))
def test_a_class_body_read_of_its_own_def_is_lifted_and_honest(
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
