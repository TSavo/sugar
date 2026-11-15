"""Twins: an unrolled loop's next item reads every name the item before it
bound, as the block reads it after the item.

```
def test_carry():
    x = 0
    seen = []
    for i in [1, 2]:
        seen.append(x)
        (x := i)
    assert <claim>
```

Python binds ``x`` in the first item before the second item reads it:
``seen`` is ``[0, 1]``, so the truthful claim is ``seen[1] == 1`` and the
lying one ``seen[1] == 0``.

The carry from one unrolled item to the next (``nodes._item_threaded``)
re-threaded the item's occurrence copies by each copy's own
``substitution_binding`` and the exposure rule, and so dropped three kinds of
binding the block takes after a statement: a walrus's (``(x := i)``), a
nested unrolled loop's final target binding (``for j in [i]: pass``, a
``_Splice`` binding) and a ``match`` capture (``case n:``, a ``_Splice``
binding).  The next item read the name as it stood before the loop, and the
lie read ``sat`` (#8869's surfaced limit).  The threading now records, for
every statement it threads, what it took from it besides its own binding
(``nodes._Taken``); the carry, the jump-owning suite and the block a
``_Splice`` reaches take those very bindings by one rule
(``nodes._thread_taken``).  So a nested statement's bindings also survive
the loop's flattening into the block after it (``nested-loop-after``).

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

_HEADER = "def test_carry():\n"
_TEST_CARRY_LINE = 1

# ``name: (body of test_carry, truthful claim, lying claim)``.
_SHAPES = {
    "for-walrus": (
        "    x = 0\n"
        "    seen = []\n"
        "    for i in [1, 2]:\n"
        "        seen.append(x)\n"
        "        (x := i)\n"
        "    assert {claim}\n",
        "seen[1] == 1",
        "seen[1] == 0",
    ),
    "for-jump-walrus": (
        "    x = 0\n"
        "    seen = []\n"
        "    for i in [1, 2]:\n"
        "        seen.append(x)\n"
        "        (x := i)\n"
        "        if i == 5:\n"
        "            break\n"
        "    assert {claim}\n",
        "seen[1] == 1",
        "seen[1] == 0",
    ),
    "while-walrus": (
        "    x = 0\n"
        "    seen = []\n"
        "    i = 0\n"
        "    while i < 2:\n"
        "        seen.append(x)\n"
        "        i += 1\n"
        "        (x := i)\n"
        "    assert {claim}\n",
        "seen[1] == 1",
        "seen[1] == 0",
    ),
    "nested-loop": (
        "    j = 0\n"
        "    seen = []\n"
        "    for i in [1, 2]:\n"
        "        seen.append(j)\n"
        "        for j in [i]:\n"
        "            pass\n"
        "    assert {claim}\n",
        "seen[1] == 1",
        "seen[1] == 0",
    ),
    "nested-loop-after": (
        "    j = 0\n"
        "    for i in [1, 2]:\n"
        "        for j in [i]:\n"
        "            pass\n"
        "    assert {claim}\n",
        "j == 2",
        "j == 0",
    ),
    "match-capture": (
        "    n = 0\n"
        "    seen = []\n"
        "    for i in [1, 2]:\n"
        "        seen.append(n)\n"
        "        match i:\n"
        "            case n:\n"
        "                pass\n"
        "    assert {claim}\n",
        "seen[1] == 1",
        "seen[1] == 0",
    ),
    "match-body": (
        "    last = 0\n"
        "    seen = []\n"
        "    for i in [1, 2]:\n"
        "        seen.append(last)\n"
        "        match i:\n"
        "            case n:\n"
        "                last = n\n"
        "    assert {claim}\n",
        "seen[1] == 1",
        "seen[1] == 0",
    ),
}


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_the_next_item_reads_every_binding_the_item_before_it_made(
    tmp_path: Path, shape: str, half: str
) -> None:
    body, truthful, lying = _SHAPES[shape]
    claim = truthful if half == "truthful" else lying
    result = run_source_through_real_solver(
        tmp_path / shape / half, _HEADER + body.format(claim=claim)
    )
    verdict = claim_verdict(result.prove_doc, claims_from_line=_TEST_CARRY_LINE)
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
