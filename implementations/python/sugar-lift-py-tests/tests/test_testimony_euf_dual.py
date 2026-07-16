# SPDX-License-Identifier: MIT OR Apache-2.0
"""A2 dual-logo class: separate test functions sharing a ground callsite.

Lane A instrument A2 (expected-discharge-got-refused) names dual logos that
mint bare `test_*::assertion` and refuse as vacuous single-constraint.
Ground callsite py.eq testimony must mint the shared `#euf#` key so ambient
cross-proof conjoin forms structural unsat (unsatisfied), not refuse.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_DUAL_CROSS_TEST = """\
def f(x):
    return x


def test_true():
    assert f(1) == 1


def test_lie():
    assert f(1) == 0
"""


def test_cross_test_dual_mints_shared_euf_key() -> None:
    payload = lift_file_payload(_DUAL_CROSS_TEST, "dual.py")
    asserts = [
        r
        for r in payload.ir
        if r.name.startswith("f#euf#") and r.name.endswith("::assertion")
    ]
    assert len(asserts) == 2
    assert {r.name for r in asserts} == {asserts[0].name}
    # Distinct RHS values on the shared left call (DTO inv, pre term-table).
    rhs = sorted(r.inv.ir_formula.args[1].value for r in asserts)
    assert rhs == [0, 1]


def test_cross_test_dual_is_unsatisfied_not_refused(tmp_path: Path) -> None:
    result = run_source_through_real_solver(tmp_path / "cross-dual", _DUAL_CROSS_TEST)
    statuses = {row.get("status") for row in result.prove_doc.get("rows", [])}
    assert "unsatisfied" in statuses or result.verdict == "unsat", (
        result.verdict,
        statuses,
        [
            (row.get("status"), (row.get("reason") or "")[:160])
            for row in result.prove_doc.get("rows", [])
        ],
    )
    assert "refused" not in statuses
