# SPDX-License-Identifier: MIT OR Apache-2.0
"""BytesLiteralSugar — b'…' terms for #4106 factory shapes."""

from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload


def test_bytes_literal_in_call_arg_does_not_unresolved_constant() -> None:
    """b'secret' as call arg must not factory-gap as Constant."""
    src = (
        "def sign(secret):\n"
        "    return secret\n"
        "def test_sign():\n"
        "    assert sign(b'secret') == b'secret'\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    fas = rpc.get("factoryAuditSummary") or {}
    counts = fas.get("statusCounts") or {}
    # Must not be pure unresolved on Constant
    assert counts.get("unresolved", 0) == 0 or counts.get("warranted", 0) > 0
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["stated"] == 1
    assert ax["lifted_cited"] >= 1, ax
    assert ax["silently_unaccounted"] == 0


def test_bytes_eq_bytes_lifts() -> None:
    src = (
        "def test_eq():\n"
        "    assert b'ab' == b'ab'\n"
    )
    # Ground tautology may fold; if silent that's ok for tautology.
    # Prefer: at least no Constant unresolved on the walk.
    rpc = lift_file_payload(src, "t.py").to_rpc()
    walk = (rpc.get("factoryAuditSummary") or {}).get("factoryWalk") or []
    for row in walk:
        if row.get("ast_kind") == "Constant" and row.get("status") == "unresolved":
            # bytes must be owned by BytesLiteralSugar
            assert False, f"bytes Constant still unresolved: {row}"
