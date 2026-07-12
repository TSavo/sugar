# SPDX-License-Identifier: MIT OR Apache-2.0
"""BuiltinTypeNameSugar — deeper floor for isinstance / type names."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload


def test_isinstance_bytes_lifts_not_silent() -> None:
    src = (
        "def test_i():\n"
        "    assert isinstance(b'ab', bytes)\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["stated"] == 1
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] == 1, ax
    assert ax["refused_loud"] == 0


def test_isinstance_with_local_var_lifts() -> None:
    src = (
        "def test_i():\n"
        "    x = b'ab'\n"
        "    assert isinstance(x, bytes)\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["stated"] == 1
    assert ax["silently_unaccounted"] == 0
    # Prefer lift; if assign binding fails, refuse-loud still ok — not silent
    assert ax["lifted_cited"] + ax["refused_loud"] == 1
    assert ax["lifted_cited"] == 1, ax


def test_unbound_user_name_still_panics_loud() -> None:
    """User names must not soft-resolve — TemporalContext panic → refuse-loud."""
    src = (
        "def test_u():\n"
        "    assert no_such_name == 1\n"
    )
    payload, gaps = audit_lift_file(src, "t.py", hold_panic=True)
    rpc = payload.to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["refused_loud"] == 1
    assert gaps[0].info["observed"] == "no_such_name"
    with pytest.raises(FactoryPanic):
        lift_file_payload(src, "t.py")


def test_method_eq_const_still_lifts() -> None:
    """Regression: method call == const already lifts (MethodCallSugar floor)."""
    src = (
        "class C:\n"
        "    def m(self):\n"
        "        return 1\n"
        "def test_m():\n"
        "    assert C().m() == 1\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["lifted_cited"] == 1
    assert ax["silently_unaccounted"] == 0
