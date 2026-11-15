"""Twins: one statement reads a rebindable name before and after a call
that rebinds it.

```
TOKEN = None
def reset():
    global TOKEN
    TOKEN = []
def test_reset():
    a = (TOKEN, reset(), TOKEN)
    assert <claim>
```

Python evaluates the tuple left to right: the first ``TOKEN`` is read
before ``reset()`` runs and the second after, so ``a[0]`` is ``None`` and
``a[2]`` the new list.  The truthful claim is ``a[0] is not a[2]``; the
lying one ``a[0] is a[2]``.

#8823 made a read of such a global after an operation that may run code
another evaluation, but only between statements: inside one statement both
reads substituted against the scope before it, the one term, so the lying
claim could fold to true and read ``sat``.  The one exposure rule now holds
between a statement's sub-expressions too
(``container_mutation.rebound_after``, ``nodes._scope_after``'s
``rebinds``): the read after ``reset()`` is the unknown it left, keyed by
that sub-expression's evaluation.  The same holds for a display, a call's
arguments, an ``or``'s later operand and a ``nonlocal`` cell.  A lying claim
is never ``sat``; a truthful one is never ``unsat``.

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
    "TOKEN = None\n"
    "\n"
    "\n"
    "def reset():\n"
    "    global TOKEN\n"
    "    TOKEN = []\n"
    "\n"
    "\n"
)

# ``name: (source, line of the test function, truthful claim, lying claim)``.
_SHAPES = {
    "tuple": (
        _RESET + "def test_reset():\n"
        "    a = (TOKEN, reset(), TOKEN)\n"
        "    assert {claim}\n",
        9,
        "a[0] is not a[2]",
        "a[0] is a[2]",
    ),
    "list": (
        _RESET + "def test_reset():\n"
        "    a = [TOKEN, reset(), TOKEN]\n"
        "    assert {claim}\n",
        9,
        "a[0] is not a[2]",
        "a[0] is a[2]",
    ),
    "call-arguments": (
        _RESET + "def pair(x, _y, z):\n"
        "    return (x, z)\n"
        "\n"
        "\n"
        "def test_reset():\n"
        "    a = pair(TOKEN, reset(), TOKEN)\n"
        "    assert {claim}\n",
        13,
        "a[0] is not a[1]",
        "a[0] is a[1]",
    ),
    "or-operand": (
        _RESET + "def test_reset():\n"
        "    before = TOKEN\n"
        "    assert {claim}\n",
        9,
        "(reset() or TOKEN) is not before",
        "(reset() or TOKEN) is before",
    ),
    "nonlocal-cell": (
        "def test_cell():\n"
        "    n = 0\n"
        "\n"
        "    def bump():\n"
        "        nonlocal n\n"
        "        n += 1\n"
        "\n"
        "    a = (n, bump(), n)\n"
        "    assert {claim}\n",
        1,
        "a[0] != a[2]",
        "a[0] == a[2]",
    ),
}


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_read_after_a_rebinding_call_in_one_statement_is_another_evaluation(
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
