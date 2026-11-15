"""Twins: a function reads a module global a module-level call changed.

```
X = []
def add(): X.append(1)
add()
def test_f(): assert <claim>
```

Python runs ``add()`` at import, so ``test_f`` sees ``X == [1]``: the
truthful claim is ``X == [1]``, the lying one ``not X``.

The module body was threaded twice (#7757 re-survey, new item 5): the
module's construction rebinds ``X`` after ``add()`` (the one exposure rule,
``container_mutation.havoc_after``), and the threading readers take module
globals from (``SourceUnit.module_binding_states``) did not, so ``test_f``
read ``X = []``'s key, whose value in the module run is the empty list
before the call. The lying claim came back ``sat``.

The readers' threading now takes the same exposure rule. After ``add()``,
``X`` is the list as the call left it, which no key decides, so a reader's
reference to it is ``undecided`` (``UNDECIDED_MODULE_BINDING``), never the
stale value: ``test_f`` is refused by name for it, its proof owes one
``undecided`` member, and the file is ``open`` for both halves. A lying claim
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

_SOURCE = (
    "X = []\n"
    "\n"
    "\n"
    "def add():\n"
    "    X.append(1)\n"
    "\n"
    "\n"
    "add()\n"
    "\n"
    "\n"
    "def test_f():\n"
    "    assert {claim}\n"
)
_TEST_F_LINE = 11
_HALVES = {"truthful": "X == [1]", "lying": "not X"}


def _refusals_of_test_f(lift_doc: dict) -> list[dict]:
    """The ``undecided`` rows the kit sent for ``test_f`` refused by name."""
    return [
        row
        for row in lift_doc["ir"]
        if row.get("kind") == "undecided"
        and "refused" in (row.get("reason") or {})
        and row["site"]["startLine"] == _TEST_F_LINE
    ]


@pytest.mark.parametrize("half", sorted(_HALVES))
def test_a_global_a_module_call_changed_is_never_read_stale(
    tmp_path: Path, half: str
) -> None:
    result = run_source_through_real_solver(
        tmp_path / half, _SOURCE.format(claim=_HALVES[half])
    )
    (refusal,) = _refusals_of_test_f(result.lift_doc)
    observed = refusal["reason"]["refused"]["observed"]
    assert "undecided module binding of `X`" in observed, refusal
    verdict = claim_verdict(result.prove_doc, claims_from_line=_TEST_F_LINE)
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
    # Undecided is the honest answer for both halves.
    assert verdict == "open", result.prove_doc
