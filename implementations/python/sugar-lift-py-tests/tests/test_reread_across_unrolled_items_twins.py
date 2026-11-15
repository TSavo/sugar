"""Twins: an unrolled loop's next item reads a rebindable name after the
call an earlier item made.

```
TOKEN = None
def bump():
    global TOKEN
    TOKEN = []
def test_reset():
    seen = []
    for i in [1, 2]:
        seen.append(TOKEN)
        bump()
    assert <claim>
```

Python runs the first item's ``bump()`` before the second item reads
``TOKEN``: ``seen`` holds ``None`` and then a new list, so the truthful claim
is ``seen[0] is not seen[1]`` and the lying one ``seen[0] is seen[1]``.

An unrolled ``for`` (and ``while``) carried into its next item what its body
statements bound (``substitution_binding``) and not what the one exposure
rule rebinds after their operations (``container_mutation.havoc_after``):
the second item read ``TOKEN`` as it stood before the loop, the one term the
first item read, and the lie could fold to true and read ``sat`` (#8865's
listed limit).  The carry now threads each item's occurrence copies as the
block threads them once the loop has dissolved (``nodes._item_threaded``):
what a call may rebind is read in the next item as the item before it left
it, keyed by that item's evaluation.  An unroll whose body owns a jump
(``For._substitute_controlled_suite``) threads the same rule within an item
and carries it between items.

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

_BUMP = (
    "TOKEN = None\n"
    "\n"
    "\n"
    "def bump():\n"
    "    global TOKEN\n"
    "    TOKEN = []\n"
    "\n"
    "\n"
    "def test_reset():\n"
)
_TEST_RESET_LINE = 9

# ``name: (body of test_reset, truthful claim, lying claim)``.
_SHAPES = {
    "for-append": (
        "    seen = []\n"
        "    for i in [1, 2]:\n"
        "        seen.append(TOKEN)\n"
        "        bump()\n"
        "    assert {claim}\n",
        "seen[0] is not seen[1]",
        "seen[0] is seen[1]",
    ),
    "for-carry": (
        "    before = TOKEN\n"
        "    last = None\n"
        "    for i in [1, 2]:\n"
        "        last = TOKEN\n"
        "        bump()\n"
        "    assert {claim}\n",
        "last is not before",
        "last is before",
    ),
    "for-jump-carry": (
        "    before = TOKEN\n"
        "    last = None\n"
        "    for i in [1, 2]:\n"
        "        last = TOKEN\n"
        "        bump()\n"
        "        if i == 5:\n"
        "            break\n"
        "    assert {claim}\n",
        "last is not before",
        "last is before",
    ),
    "for-jump-within": (
        "    before = TOKEN\n"
        "    last = None\n"
        "    for i in [1]:\n"
        "        bump()\n"
        "        last = TOKEN\n"
        "        if i == 5:\n"
        "            break\n"
        "    assert {claim}\n",
        "last is not before",
        "last is before",
    ),
    "while-carry": (
        "    before = TOKEN\n"
        "    last = None\n"
        "    i = 0\n"
        "    while i < 2:\n"
        "        last = TOKEN\n"
        "        bump()\n"
        "        i += 1\n"
        "    assert {claim}\n",
        "last is not before",
        "last is before",
    ),
}


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_name_an_item_call_rebinds_is_another_evaluation_in_the_next_item(
    tmp_path: Path, shape: str, half: str
) -> None:
    body, truthful, lying = _SHAPES[shape]
    claim = truthful if half == "truthful" else lying
    result = run_source_through_real_solver(
        tmp_path / shape / half, _BUMP + body.format(claim=claim)
    )
    verdict = claim_verdict(result.prove_doc, claims_from_line=_TEST_RESET_LINE)
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
