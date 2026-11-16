"""Twins: an item store or delete nothing decides on a decided container
is the one undecided item mutation (#7757, audit 4 row NEW-9).

A decided ``list`` / ``dict`` whose index or key is not decided once
answered ``store_faces``: a completion whose value was a
``RuntimeEffectTestimony`` of the store, keyed per site
(``python:store_completed("store-outcome:<file>:<line>:<col>", ...)``).  A
guarded receiver (``[1, 2] if c else [3, 4]``) takes each arm's store
through the one door, and the name it is bound to takes the store's
completed value as the receiver after it.  That value is now the
receiver's unknown after-state, ``python:receiver_after_call(<occurrence>,
<method>)``, keyed per evaluation, which prove decides a claim over for
every value of it (``consistency::UNDETERMINED_STATES``): nothing reads
the list or dict as unchanged, and nothing is read off the store.

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

# ``name: (source, truthful claim, lying claim)``.
_SHAPES = {
    "list-store-undecided-index": (
        "def g(c, i):\n"
        "    xs = [1, 2] if c else [3, 4]\n"
        "    xs[i] = 9\n"
        "    return xs[0]\n"
        "\n"
        "\n"
        "def test_g():\n"
        "    assert {claim}\n",
        "g(True, 0) == 9",
        "g(True, 0) == 1",
    ),
    "dict-delete-undecided-key": (
        "def g(c, k):\n"
        # Braces doubled: the source is a ``str.format`` template.
        '    d = {{"a": 1}} if c else {{"b": 2}}\n'
        "    del d[k]\n"
        "    return len(d)\n"
        "\n"
        "\n"
        "def test_g():\n"
        "    assert {claim}\n",
        'g(True, "a") == 0',
        'g(True, "a") == 1',
    ),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows the helper."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_an_item_mutation_nothing_decides_never_refutes_a_truth_nor_admits_a_lie(
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
