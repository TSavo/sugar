"""Solver twin for #7766: every assertion site's row reaches the real solver.

The one difference between the two sources is the claimed value. The floor
decides ``double(3)`` (a same-file call it can construct), so the truthful
assert states the decided fact ``true`` and the lying assert is reached by no
completed arm and states ``false``. Both rows go through real ``sugar mint``
and real ``sugar prove``; the verdict is the solver's, not the lifter's.
Revert the emitter (first-row-only ``universe`` scan, or ground True stating
nothing) and the truthful twin has no assertion row: no verdict.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_TWIN = (
    "def double(x):\n"
    "    return x + x\n"
    "\n"
    "\n"
    "def test_double():\n"
    "    assert double(3) == {claim}\n"
)


def test_a_decided_assertion_reaches_the_solver(tmp_path: Path) -> None:
    truthful = run_source_through_real_solver(tmp_path / "t", _TWIN.format(claim=6))
    lying = run_source_through_real_solver(tmp_path / "l", _TWIN.format(claim=7))
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
