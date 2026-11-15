"""Twins: a store target reads a rebindable name after code the same
statement ran before it.

```
TOKEN = 0
def reset():
    global TOKEN
    TOKEN = 1
    return 0
def test_reset():
    before = TOKEN
    d = {}
    d[TOKEN] = reset()
    assert <claim>
```

Python evaluates an assignment's value before its targets: ``reset()``
runs first, so ``d[TOKEN]`` reads the new ``TOKEN`` and stores under ``1``.
``before`` (``0``) is not a key.  The truthful claim is ``before not in d``;
the lying one ``before in d``.

#8847 made a read of such a name after a code-running sub-expression of one
statement another evaluation (``container_mutation.rebound_after``,
``nodes._scope_after``'s ``rebinds``), but a store target read its receiver
and key by another route, against the scope before the statement: the key
was the read ``before`` holds, the one term, so the lying claim could fold
to true and read ``sat``.  The target is now read in the scope the value
leaves, its key in the scope its receiver leaves, and what follows a target
(a later target, an augmented store's value) in the scope the target and
the dunder run on its receiver leave (``nodes._substituted_store_target_parts``,
``nodes._scope_after_store_target``): the same door, in Python's order.

Shapes: a single subscript store, an unpack's store leaf, a chain's store
target, an augmented store's value read after its key's call
(``a[reset()] += TOKEN``: the key, the item read, then the value), and a
``nonlocal`` cell.  A lying claim is never ``sat``; a truthful one is never
``unsat``.

Each half goes through ``run_source_through_real_solver``: real ``sugar
mint`` then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

_RESET = (
    "TOKEN = 0\n"
    "\n"
    "\n"
    "def reset():\n"
    "    global TOKEN\n"
    "    TOKEN = 1\n"
    "    return 0\n"
    "\n"
    "\n"
)

# ``name: (source, line of the test function, truthful claim, lying claim)``.
_SHAPES = {
    "subscript": (
        _RESET + "def test_reset():\n"
        "    before = TOKEN\n"
        "    d = {{}}\n"
        "    d[TOKEN] = reset()\n"
        "    assert {claim}\n",
        10,
        "before not in d",
        "before in d",
    ),
    "unpack-leaf": (
        _RESET + "def test_reset():\n"
        "    before = TOKEN\n"
        "    d = {{}}\n"
        "    d[TOKEN], b = reset(), 1\n"
        "    assert {claim}\n",
        10,
        "before not in d",
        "before in d",
    ),
    "chain-target": (
        _RESET + "def test_reset():\n"
        "    before = TOKEN\n"
        "    d = {{}}\n"
        "    b = d[TOKEN] = reset()\n"
        "    assert {claim}\n",
        10,
        "before not in d",
        "before in d",
    ),
    "augmented-value": (
        _RESET + "def test_reset():\n"
        "    before = TOKEN\n"
        "    a = [0]\n"
        "    a[reset()] += TOKEN\n"
        "    assert {claim}\n",
        10,
        "a[0] != before",
        "a[0] == before",
    ),
    "nonlocal-cell": (
        "def test_cell():\n"
        "    n = 0\n"
        "\n"
        "    def bump():\n"
        "        nonlocal n\n"
        "        n += 1\n"
        "\n"
        "    before = n\n"
        "    d = {{}}\n"
        "    d[n] = bump()\n"
        "    assert {claim}\n",
        1,
        "before not in d",
        "before in d",
    ),
}


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_store_target_read_after_a_rebinding_call_is_another_evaluation(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, line, truthful, lying = _SHAPES[shape]
    claim = truthful if half == "truthful" else lying
    result = run_source_through_real_solver(
        tmp_path / shape / half, source.format(claim=claim)
    )
    verdict = claim_verdict(result.prove_doc, claims_from_line=line)
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
