"""Plan row 1 (step 6): a method called on a class call's result is the one method call.

``Box(3).get()`` and ``b = Box(3); b.get()`` are the same call: the receiver is
whatever the class call built, and the method is selected on that receiver and
applied through the one routine (``ObjectValue.call_method_value`` ending in
``CallSiteValue.producer_outcome``).

There used to be a second entry for the inline shape when the class came from an
authenticated import: preconstruction chose the method frame from the class
statement and ``Call._construct_sugar`` picked ``MethodCallSugar`` with that
frame by a ``dispatch_kind == "method"`` flag. That entry is deleted. The
one-file solver harness cannot stage an imported distribution, so the twins
below state the rule on a same-file class; the imported shape is covered in
process by ``sugar-lift-python-source/tests/test_source_call_preconstruction.py``.

Each twin differs in one literal, truthful ``sat``, lying ``unsat``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_CLASS = (
    "class Box:\n"
    "    def __init__(self, n):\n"
    "        self.n = n\n"
    "\n"
    "    def get(self, k):\n"
    "        return self.n + k\n"
    "\n"
    "\n"
)

_SHAPES = {
    "inline": _CLASS + "def test_box():\n    assert Box(3).get(4) == {claim}\n",
    "assigned": _CLASS
    + "def test_box():\n    b = Box(3)\n    assert b.get(4) == {claim}\n",
}


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_method_on_a_class_call_result_reaches_the_solver(
    shape: str, tmp_path: Path
) -> None:
    source = _SHAPES[shape]
    truthful = run_source_through_real_solver(tmp_path / "t", source.format(claim=7))
    lying = run_source_through_real_solver(tmp_path / "l", source.format(claim=8))
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
