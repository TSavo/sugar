"""Twins: a function reads a module global before and after a call that
rebinds it.

```
TOKEN = None
def reset():
    global TOKEN
    TOKEN = []
def test_reset():
    before = TOKEN
    reset()
    assert <claim>
```

Python runs ``reset()`` inside ``test_reset``, which rebinds ``TOKEN`` to a
new list: ``before`` is the old object, so the truthful claim is ``before is
not TOKEN`` and the lying one ``before is TOKEN``.

``TOKEN`` is written through a ``global`` declaration, so the module body
does not decide it and ``test_reset`` reads it through its undecided key,
its free ``global:TOKEN`` input (#8802).  Both reads used to read that one
input, so ``before is TOKEN`` was a comparison of one term with itself and
the lying claim could fold to true and read ``sat`` (#8802's known limit).

A call that may run code rebinding a global some body writes through a
``global`` declaration now rebinds the name in the caller's frame
(``container_mutation._frame_globals``): the read after ``reset()`` is
another evaluation, the unknown that call left, keyed by the call's
evaluation.  A lying claim is never ``sat``; a truthful one is never
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

_SOURCE = (
    "TOKEN = None\n"
    "\n"
    "\n"
    "def reset():\n"
    "    global TOKEN\n"
    "    TOKEN = []\n"
    "\n"
    "\n"
    "def test_reset():\n"
    "    before = TOKEN\n"
    "    reset()\n"
    "    assert {claim}\n"
)
_TEST_RESET_LINE = 9
_HALVES = {"truthful": "before is not TOKEN", "lying": "before is TOKEN"}


@pytest.mark.parametrize("half", sorted(_HALVES))
def test_a_global_read_after_a_rebinding_call_is_another_evaluation(
    tmp_path: Path, half: str
) -> None:
    result = run_source_through_real_solver(
        tmp_path / half, _SOURCE.format(claim=_HALVES[half])
    )
    verdict = claim_verdict(result.prove_doc, claims_from_line=_TEST_RESET_LINE)
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
