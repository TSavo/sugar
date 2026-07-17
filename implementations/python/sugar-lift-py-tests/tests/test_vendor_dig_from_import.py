# SPDX-License-Identifier: MIT OR Apache-2.0
"""Vendor dig foundations: TupleValue.to_term + from_imports maps on ctx."""

from __future__ import annotations

from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import (
    _module_import_maps,
    lift_file_payload,
)


def test_tuple_return_eq_literal_lifts() -> None:
    """Vendor-style (payload, ts) equality needs TupleValue.to_term."""
    src = (
        "def f():\n"
        "    return (1, 2)\n"
        "def test_t():\n"
        "    assert f() == (1, 2)\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    reasons = " ".join(
        str(r.get("reason") or "")
        for r in ((rpc.get("factoryAuditSummary") or {}).get("unresolvedSites") or [])
    )
    assert "TupleValue" not in reasons or "project this floor" not in reasons, reasons
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] == 1, ax


def test_module_import_maps_from_import() -> None:
    src = (
        "from itsdangerous import Signer\n"
        "from itsdangerous.signer import HMACAlgorithm as HA\n"
        "import pytest\n"
        "def test_x():\n"
        "    assert True\n"
    )
    mod = SourceFragment.from_source(src, "t.py").statements()[0]
    aliases, from_imports = _module_import_maps(mod)
    assert from_imports.get("Signer") == ("itsdangerous", "Signer")
    assert from_imports.get("HA") == ("itsdangerous.signer", "HMACAlgorithm")
    assert aliases.get("pytest") == "pytest"


def test_module_import_maps_qualifies_relative_package_import(tmp_path) -> None:
    package = tmp_path / "pkg" / "tests"
    package.mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    filename = package / "test_case.py"
    src = "from . import util\n"
    mod = SourceFragment.from_source(src, str(filename)).statements()[0]

    _aliases, from_imports = _module_import_maps(mod, str(filename))

    assert from_imports["util"] == ("pkg.tests", "util")

    call = (
        SourceFragment.from_source("util.managed()", str(filename))
        .statements()[0]
        .statements()[0]
        .expr_value()
    )
    assert call.call_import_target_name({}, from_imports) == "pkg.tests.util.managed"


def test_audit_ctx_carries_from_imports() -> None:
    """FactoryBuildContext must receive from_imports (not temporal alone)."""
    src = (
        "from itsdangerous import Signer\n"
        "def test_s():\n"
        "    s = Signer('k')\n"
        "    assert s is not None\n"
    )
    # Smoke: lifts or refuses, but factory maps must be populated when building.
    # We re-derive maps the same way audit_lift_file does.
    mod = SourceFragment.from_source(src, "t.py").statements()[0]
    aliases, from_imports = _module_import_maps(mod)
    ctx = FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        import_aliases=aliases,
        from_imports=from_imports,
    )
    assert ctx.from_imports["Signer"] == ("itsdangerous", "Signer")
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0


def test_vendor_sign_unsign_still_lifts_as_coordinate() -> None:
    src = (
        "from itsdangerous import Signer\n"
        "def test_s():\n"
        "    s = Signer('secret-key')\n"
        "    assert s.unsign(s.sign('value')) == b'value'\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] == 1, ax
