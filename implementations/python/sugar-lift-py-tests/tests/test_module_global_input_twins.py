"""Twins: a test function reads a module global its contract names as an input.

```
X = 3
def test_x(): assert X == <n>
```

``test_x`` reads ``X`` when pytest calls it, after import, so its contract
states ``global:X`` as an input (#7757 step 4) and its claim is stated over
the free input (step 5). The row states the value the module's one run left
for it, 3, and prove's one binder binds the input to it, as pytest's call
after import supplies nothing (``consistency::bind_own_inputs``). The
truthful claim ``X == 3`` is ``sat``, the lying ``X == 4`` ``unsat``, as
before.

Each half goes through ``run_source_through_real_solver``: real ``sugar
mint`` then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

_SOURCE = "X = 3\n\n\ndef test_x():\n    assert X == {n}\n"
_TEST_X_LINE = 4
_HALVES = {"truthful": (3, "sat"), "lying": (4, "unsat")}


@pytest.mark.parametrize("half", sorted(_HALVES))
def test_a_root_reads_its_global_input_at_the_module_final_value(
    tmp_path: Path, half: str
) -> None:
    n, expected = _HALVES[half]
    result = run_source_through_real_solver(tmp_path / half, _SOURCE.format(n=n))
    verdict = claim_verdict(result.prove_doc, claims_from_line=_TEST_X_LINE)
    assert verdict == expected, result.prove_doc
