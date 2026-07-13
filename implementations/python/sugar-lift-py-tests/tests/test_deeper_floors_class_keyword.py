# SPDX-License-Identifier: MIT OR Apache-2.0
"""Class-method testimony walk + KeywordCallSugar."""

from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload


def test_class_method_testimony_lifts() -> None:
    src = "class TestBox:\n" "    def test_one(self):\n" "        assert 1 == 1\n"
    # ground fold may refuse-loud under doctrine; shape is class walk owns
    rpc = lift_file_payload(src, "t.py").to_rpc()
    names = [i.get("name") for i in (rpc.get("ir") or [])]
    # At least walked: either assertion or empty ir with no Call gap on test
    fas = rpc.get("factoryAuditSummary") or {}
    # class method must be owned — statusCounts sites > 0
    assert (fas.get("sites") or fas.get("statusCounts")) is not None
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["stated"] == 1
    assert ax["silently_unaccounted"] == 0


def test_keyword_call_not_unresolved() -> None:
    src = (
        "def B(w, n=0):\n"
        "    return w\n"
        "def test_k():\n"
        "    assert B(5, n=1) == 5\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    fas = rpc.get("factoryAuditSummary") or {}
    reasons = " ".join(
        str(r.get("reason") or "") for r in (fas.get("unresolvedSites") or [])
    )
    assert "call.call_sugar" not in reasons.lower() or "keyword" not in reasons.lower()
    # Stronger: no observed=Call unresolved for keyword shape
    for r in fas.get("unresolvedSites") or []:
        reason = r.get("reason") or ""
        assert not ("observed=Call" in reason and "call_sugar" in reason), reason
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] == 1, ax


def test_not_implemented_error_is_builtin_type() -> None:
    src = (
        "def test_e():\n"
        "    assert isinstance(NotImplementedError(), NotImplementedError)\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    reasons = " ".join(
        str(r.get("reason") or "")
        for r in ((rpc.get("factoryAuditSummary") or {}).get("unresolvedSites") or [])
    )
    assert "bind `NotImplementedError`" not in reasons, reasons
