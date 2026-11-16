"""Twins: a display substitution cannot pair is unpacked at reduce (#7757 S2).

An unpack had two mechanisms: substitution paired a display right-hand side
with its targets member by member, and the reduce-time unpack read the
value of every other right-hand side.  A display the pairing could not take
-- a nested level whose member is no display
(``a, (b, c) = 1, [x for x in range(2)]``), a store leaf under a nested
level (``a, (b, xs[0]) = 1, (2, 3)``) -- refused the statement and its
function by name, and its ``range(...)`` call was never built.

Python builds the display, then unpacks it.  Such a statement now takes the
one reduce-time unpack of its one evaluation
(``Assign._dynamic_unpack_target``): the display is built, its members and
their halts kept, and the unpack reads the decided tuple it reduces to.

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

# ``name: (source, truthful claim, lying claim)``.  Braces are doubled: the
# source is a ``str.format`` template.
_SHAPES = {
    # The inner level is a comprehension, not a display.
    "nested-comprehension-level": (
        "def test_a():\n"
        "    a, (b, c) = 1, [x for x in range(2)]\n"
        "    assert {claim}\n",
        "c == 1",
        "c == 0",
    ),
    # A store leaf under a nested level: neither display pairing takes it.
    "store-leaf-under-nested-level": (
        "def test_a():\n"
        "    xs = [0]\n"
        "    a, (b, xs[0]) = 1, (2, 3)\n"
        "    assert {claim}\n",
        "xs[0] == 3",
        "xs[0] == 2",
    ),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_an_unpaired_display_unpack_never_refutes_a_truth_nor_admits_a_lie(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, truthful, lying = _SHAPES[shape]
    text = source.format(claim=truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
