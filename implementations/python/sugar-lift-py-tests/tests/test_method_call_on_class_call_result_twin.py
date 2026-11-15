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

The receiver is made in the test function, so inside the applied bodies
``self`` is the caller's current object and ``self.n + k`` is ``3 + 4``: the
test function's claim is decided.  ``__init__``'s and ``get``'s OWN proofs
have no caller: there ``self.n = n`` and ``self.n + k`` act on formals with no
actual, and each owes an ``undecided`` member of the source (step 8).  A
source that owes anything is never ``sat`` as a whole, so the truthful half
is read on the test function's own claims (``witness_harness.claim_verdict``):
the members the methods' own proofs owe sit above the test function and are
set aside; the lying half is refuted through ``prove_verdict`` unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

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
    # The test function is the one ``def test_`` line; every method above it.
    (test_line,) = (
        number
        for number, line in enumerate(source.splitlines(), start=1)
        if line.startswith("def test_")
    )
    assert claim_verdict(truthful.prove_doc, claims_from_line=test_line) == "sat"
    assert lying.verdict == "unsat"
