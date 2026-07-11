# SPDX-License-Identifier: MIT OR Apache-2.0
"""SliceSubscriptSugar, NotInOpSugar, ChainedCompareSugar."""

from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload


def test_slice_not_unresolved() -> None:
    src = "def test_s():\n    b = b'abc'\n    assert b[:-1] == b'ab'\n"
    rpc = lift_file_payload(src, "t.py").to_rpc()
    reasons = " ".join(
        str(r.get("reason") or "")
        for r in ((rpc.get("factoryAuditSummary") or {}).get("unresolvedSites") or [])
    )
    assert "observed=Subscript" not in reasons or "Slice" not in reasons
    assert "slice" not in reasons.lower() or "unresolved" not in reasons
    # Stronger: no Subscript gap at all for slice form
    for r in (rpc.get("factoryAuditSummary") or {}).get("unresolvedSites") or []:
        assert "observed=Subscript" not in (r.get("reason") or ""), r
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] == 1, ax


def test_not_in_lifts() -> None:
    src = "def test_n():\n    assert 'x' not in 'abc'\n"
    rpc = lift_file_payload(src, "t.py").to_rpc()
    for r in (rpc.get("factoryAuditSummary") or {}).get("unresolvedSites") or []:
        assert "observed=Compare" not in (r.get("reason") or ""), r
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] == 1, ax


def test_chained_compare_lifts() -> None:
    src = "def test_c():\n    assert 1 < 2 < 3\n"
    rpc = lift_file_payload(src, "t.py").to_rpc()
    for r in (rpc.get("factoryAuditSummary") or {}).get("unresolvedSites") or []:
        assert "observed=Compare" not in (r.get("reason") or ""), r
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] == 1, ax
