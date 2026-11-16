"""Twins: a read of a field a class's construction stored is the field only
where prove decides it is the ``__dict__`` entry (#7757 H1a).

A class's constructor contract stated that a caller's read of each field
its construction set completes with the stored value wherever the lift's
own walk (``ObjectValue.reads_plain_field``) said the read was plain.  That
walk never asked ``__slots__``: for

    class P:
        __slots__ = ('x',)
        def __init__(self):
            self.x = 1
            self.y = 2

it stated ``P().y`` completes with ``2``, although Python raises
``AttributeError`` at ``self.y = 2`` and no instance of ``P`` ever holds
``y``.  The read is now stated under ``python:plain_read(<class>, "<f>")``,
which prove alone decides on the namespace rows
(``consistency::plain_read_holds``: ``__slots__`` is one of its hooks), so
the read of a slotted class's field stays owed.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each
half goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

# A store outside ``__slots__`` raises ``AttributeError``: no instance of
# ``P`` holds ``y``, so a claim that reads ``y`` as ``2`` is a lie.  (The
# truthful claim on this source -- that ``P()`` raises -- is the store's,
# #7757 H1b.)
_STORE_OUTSIDE_SLOTS = (
    "class P:\n"
    "    __slots__ = ('x',)\n"
    "\n"
    "    def __init__(self):\n"
    "        self.x = 1\n"
    "        self.y = 2\n"
    "\n"
    "\n"
    "def test_p():\n"
    "    assert {claim}\n"
)

# A store inside ``__slots__`` completes: ``x`` is the slot's member
# descriptor, read back as ``1``.
_STORE_INSIDE_SLOTS = (
    "class Q:\n"
    "    __slots__ = ('x',)\n"
    "\n"
    "    def __init__(self):\n"
    "        self.x = 1\n"
    "\n"
    "\n"
    "def test_q():\n"
    "    assert {claim}\n"
)

# ``name: (source, claim, half)``.
_CASES = {
    "store-outside-slots-read-lying": (_STORE_OUTSIDE_SLOTS, "P().y == 2", "lying"),
    "slot-field-read-truthful": (_STORE_INSIDE_SLOTS, "Q().x == 1", "truthful"),
    "slot-field-read-lying": (_STORE_INSIDE_SLOTS, "Q().x == 2", "lying"),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows the class."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("case", sorted(_CASES))
def test_a_slotted_field_read_never_refutes_a_truth_nor_admits_a_lie(
    tmp_path: Path, case: str
) -> None:
    source, claim, half = _CASES[case]
    text = source.format(claim=claim)
    result = run_source_through_real_solver(tmp_path / case, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
