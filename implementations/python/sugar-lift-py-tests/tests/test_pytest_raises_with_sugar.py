# SPDX-License-Identifier: MIT OR Apache-2.0
"""RaiseSugar + PytestRaisesWithSugar — raises testimony floor."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload


def _audit_rpc(source: str) -> dict:
    payload, _gaps = audit_lift_file(source, "t.py", hold_panic=True)
    with pytest.raises(FactoryPanic):
        lift_file_payload(source, "t.py")
    return payload.to_rpc()


def test_raise_statement_not_unresolved() -> None:
    src = (
        "def boom():\n"
        "    raise ValueError('x')\n"
        "def test_b():\n"
        "    assert True\n"
    )
    rpc = _audit_rpc(src)
    reasons = " ".join(
        str(r.get("reason") or "")
        for r in ((rpc.get("factoryAuditSummary") or {}).get("unresolvedSites") or [])
    )
    assert "raise.raise_sugar" not in reasons
    assert "observed=Raise" not in reasons, reasons


def test_pytest_raises_states_inv() -> None:
    src = (
        "import pytest\n"
        "def test_r():\n"
        "    with pytest.raises(ValueError):\n"
        "        boom()\n"
        "    assert 1 == 1\n"
        "def boom():\n"
        "    raise ValueError('x')\n"
    )
    rpc = _audit_rpc(src)
    fas = rpc.get("factoryAuditSummary") or {}
    reasons = " ".join(
        str(r.get("reason") or "") for r in (fas.get("unresolvedSites") or [])
    )
    assert "observed=Raise" not in reasons, reasons
    # testimony should include pytest.raises inv and the assert
    ir = rpc.get("ir") or []
    names = [i.get("name") for i in ir]
    assert any(n and "assertion" in str(n) for n in names) or any(
        "pytest.raises" in str(i) for i in ir
    ), (names, ir[:3])
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    # ground assert may lift or refuse; raises path must not silent
    assert ax["lifted_cited"] + ax["refused_loud"] == ax["stated"]


def test_pytest_raises_as_exc_info_binds() -> None:
    src = (
        "import pytest\n"
        "def boom():\n"
        "    raise ValueError('missing key')\n"
        "def test_r():\n"
        "    with pytest.raises(ValueError) as exc_info:\n"
        "        boom()\n"
        "    assert 'missing' in str(exc_info.value)\n"
    )
    rpc = _audit_rpc(src)
    reasons = " ".join(
        str(r.get("reason") or "")
        for r in ((rpc.get("factoryAuditSummary") or {}).get("unresolvedSites") or [])
    )
    assert "bind `exc_info`" not in reasons, reasons
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["stated"] == 1


def test_raises_message_in_str_lifts() -> None:
    src = (
        "import pytest\n"
        "def boom():\n"
        "    raise ValueError('missing key')\n"
        "def test_r():\n"
        "    with pytest.raises(ValueError) as exc_info:\n"
        "        boom()\n"
        "    assert 'missing' in str(exc_info.value)\n"
    )
    rpc = _audit_rpc(src)
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["stated"] == 1
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] == 1, ax
