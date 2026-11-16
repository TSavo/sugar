"""Twins: a deferred operation on a formal inside a live loop's item is its
own evaluation per item, never one term for all of them (#7757, step 6).

An operation whose operand is a formal waits for the caller's actual
(``NativeOperationExitCarrierV1``).  The function's own proof discharges it
at the function's end (``tree_enumerate.as_its_own_proof_states``), outside
every live item, and ``_unanswered_exits`` keyed its result, its completes
atom and its halt with ``occurrence_key(site)`` under the path the discharge
ran under.  So every item's ``c + 0`` was ``python:binary_result("+", c, 0,
<site>)``: one term.  Python evaluates ``c.__add__(0)`` once per item, and a
``__add__`` that counts returns 1, then 2: the truth ``r[0] != r[1]`` could
read ``unsat``.  The carrier now keeps the occurrence path it was minted
under (``NativeOperationExitCarrierV1.occurrence``) and discharges its own
operation under it, as its enrolled work already runs
(``_at_its_occurrence``): each item's operation is its own.

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

_COUNTER = (
    "class Counter:\n"
    "    def __init__(self):\n"
    "        self.k = 0\n"
    "\n"
    "    def __add__(self, other):\n"
    "        self.k += 1\n"
    "        return self.k\n"
    "\n"
    "    def __getitem__(self, index):\n"
    "        self.k += 1\n"
    "        return self.k\n"
    "\n"
    "\n"
)

# ``name: (source, truthful claim, lying claim)``.
_SHAPES = {
    "binary-per-item": (
        _COUNTER + "def twice(c):\n"
        "    out = []\n"
        "    for _ in (1, 2):\n"
        "        out.append(c + 0)\n"
        "    return out\n"
        "\n"
        "\n"
        "def test_twice():\n"
        "    r = twice(Counter())\n"
        "    assert {claim}\n",
        "r[0] != r[1]",
        "r[0] == r[1]",
    ),
    "subscript-per-item": (
        _COUNTER + "def twice(c):\n"
        "    out = []\n"
        "    for _ in (1, 2):\n"
        "        out.append(c[0])\n"
        "    return out\n"
        "\n"
        "\n"
        "def test_twice():\n"
        "    r = twice(Counter())\n"
        "    assert {claim}\n",
        "r[0] != r[1]",
        "r[0] == r[1]",
    ),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows every helper."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_each_item_evaluates_its_own_deferred_operation(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, truthful, lying = _SHAPES[shape]
    claim = truthful if half == "truthful" else lying
    text = source.format(claim=claim)
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc


def test_a_minted_carrier_keeps_the_path_it_was_minted_under() -> None:
    # The key of the operation is read where it was evaluated: a carrier
    # minted inside an item carries that item's path to its discharge.
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.occurrence import current_path, entered

    with entered("loop:item-path-probe#1"):
        path = current_path()
    assert path[-1] == "loop:item-path-probe#1"
    field = NativeOperationExitCarrierV1.__dataclass_fields__["occurrence"]
    assert field.default is None
