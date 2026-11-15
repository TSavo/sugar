"""`sugar mint` and the board's door read different content for the same file (#7796).

Plan row 5 (the board reads the one lift). Measured on main at ``af341f3cd``
with a 16-line module: a same-module context manager class, a function that
enters it, and a test function.

When measured, ``sugar mint`` refused the ``with`` while the board's door
built it from a table a population pre-pass seated at file open.  That
pre-pass is deleted (#7757): no door reads a callee body before construction,
and the ``with``'s manager is what its head reduces to, the same in every
door.

The twin below states what the module's proof should say; it is a plain test,
not skipped and not marked.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_MODULE = (
    "class Resource:\n"
    "    def __init__(self, target):\n"
    "        self.target = target\n"
    "    def __enter__(self):\n"
    "        return self.target\n"
    "    def __exit__(self, *exc):\n"
    "        pass\n"
    "\n"
    "\n"
    "def f():\n"
    "    with Resource(1) as value:\n"
    "        return value\n"
    "\n"
    "\n"
    "def test_f():\n"
    "    assert f() == {claim}\n"
)


def test_a_with_over_a_same_module_manager_reaches_the_solver(tmp_path: Path) -> None:
    """RED on main: ``f()`` enters ``Resource(1)`` and returns 1.

    The truthful claim is ``sat`` and the lying one ``unsat`` once mint builds
    the ``with`` the board's door already builds.
    """
    truthful = run_source_through_real_solver(tmp_path / "t", _MODULE.format(claim=1))
    lying = run_source_through_real_solver(tmp_path / "l", _MODULE.format(claim=2))
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
