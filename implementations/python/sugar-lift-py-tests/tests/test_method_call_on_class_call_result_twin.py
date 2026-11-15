"""Plan row 1 (step 6): a method called on a class call's result is one call,
and its dispatch waits for prove.

``Box(3).get()`` and ``b = Box(3); b.get()`` are the same call.  Since #7757
step 6 the class call is its coordinate and an edge to ``python:<m>.Box``,
joined at prove to the class's constructor contract: the reduction builds no
instance, so ``get`` is a method of a call's result, whose dispatch is not
decided at the reduction (``CallSiteValue.attribute``: the one undecided
read) and not at prove until the owner rules on dispatch at prove (#7757
survey step 8).  Before step 6 both halves were decided at the reduction by
following ``Box``'s constructor and ``get``'s body (truthful ``sat``, lying
``unsat``); both are now ``open``, never ``sat`` for the lie, and listed on
#7661.

There used to be a second entry for the inline shape when the class came from an
authenticated import: preconstruction chose the method frame from the class
statement and ``Call._construct_sugar`` picked ``MethodCallSugar`` with that
frame by a ``dispatch_kind == "method"`` flag. That entry is deleted.
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
    assert claim_verdict(truthful.prove_doc, claims_from_line=test_line) == "open"
    assert lying.verdict == "open"
