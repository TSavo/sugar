# SPDX-License-Identifier: MIT OR Apache-2.0
"""Deeper floors: Call==Name assign, import seeding, pytest module name."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload


def test_call_eq_name_via_assign_lifts() -> None:
    """Cmp(Call, Eq, Name) after assign — testimony path (test_ prefix)."""
    src = (
        "def claimed():\n"
        "    return 1\n"
        "def test_claimed():\n"
        "    got = claimed()\n"
        "    assert got == 1\n"
    )
    payload, gaps = audit_lift_file(src, "t.py", hold_panic=True)
    rpc = payload.to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["stated"] == 1
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] == 1, ax


def test_import_pytest_binds_name() -> None:
    src = "import pytest\n" "def test_x():\n" "    assert pytest is not None\n"
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    # Prefer lift; refuse-loud still lawful if is/identity needs more floor
    assert ax["lifted_cited"] + ax["refused_loud"] == 1
    fas = rpc.get("factoryAuditSummary") or {}
    # Must not TemporalContext-unbound pytest
    reasons = " ".join(
        str(r.get("reason") or "") for r in (fas.get("unresolvedSites") or [])
    )
    assert "bind `pytest`" not in reasons, reasons


def test_bare_pytest_module_name_without_import() -> None:
    """BuiltinModuleNameSugar: bare pytest Name has a floor."""
    src = "def test_x():\n" "    assert pytest is not None\n"
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    reasons = " ".join(
        str(r.get("reason") or "")
        for r in ((rpc.get("factoryAuditSummary") or {}).get("unresolvedSites") or [])
    )
    assert "bind `pytest`" not in reasons, reasons


def test_from_import_binds_name() -> None:
    src = (
        "from itsdangerous import Signer\n"
        "def test_s():\n"
        "    assert Signer is not None\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    reasons = " ".join(
        str(r.get("reason") or "")
        for r in ((rpc.get("factoryAuditSummary") or {}).get("unresolvedSites") or [])
    )
    assert "bind `Signer`" not in reasons, reasons


def test_imported_type_shadows_builtin_module_fallback() -> None:
    src = (
        "from datetime import datetime\n"
        "def test_datetime(value):\n"
        "    assert isinstance(value, datetime)\n"
    )

    rpc = lift_file_payload(src, "t.py").to_rpc()
    axis = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]

    assert axis["lifted_cited"] == 1
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    assert "python:module" not in repr(rpc["ir"])


def test_unbound_user_module_still_panics() -> None:
    src = "def test_x():\n" "    assert totally_unknown_pkg.foo == 1\n"
    payload, gaps = audit_lift_file(src, "t.py", hold_panic=True)
    rpc = payload.to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["refused_loud"] + ax["lifted_cited"] == 1
    assert gaps[0].info["observed"] == "totally_unknown_pkg"
    with pytest.raises(FactoryPanic):
        lift_file_payload(src, "t.py")
    assert gaps[0].info["observed"] == "totally_unknown_pkg"
    with pytest.raises(FactoryPanic):
        lift_file_payload(src, "t.py")


def test_parametrized_test_function_still_testimony() -> None:
    """@pytest.mark.parametrize must not exclude test_* from testimony owns."""
    src = (
        "import pytest\n"
        "@pytest.mark.parametrize('x', [1])\n"
        "def test_p(x):\n"
        "    assert x == 1\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["stated"] == 1
    assert ax["silently_unaccounted"] == 0
    # The exact literal row now reduces independently.  Its assertion is the
    # ground tautology ``1 == 1`` and therefore remains on the existing loud
    # ground-true assertion frontier rather than being overstated as a
    # symbolic universal fact.
    assert ax["lifted_cited"] == 0, ax
    assert ax["refused_loud"] == 1, ax
    names = [i.get("name") for i in (rpc.get("ir") or [])]
    assert not any(n and n.endswith("::assertion") for n in names), names
