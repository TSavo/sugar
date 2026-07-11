# SPDX-License-Identifier: MIT OR Apache-2.0
"""Doctrine: panic is correct for unimplemented; silent is the defect."""

from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.sugar.sugar_base import validate_registry


def test_registry_rejects_incomplete_construction_by_construction() -> None:
    """Incorrect construction is impossible: validate_registry is load-time law."""
    validate_registry()  # must not raise on the live catalog


def test_unimplemented_shape_refuses_loud_not_silent() -> None:
    """When factory cannot build, stated assert is refuse-loud — panic path."""
    # Nested For without ForSugar historically gaps; assert inside still stated.
    src = (
        "def test_loop():\n"
        "    for x in [1]:\n"
        "        assert x == 1\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["stated"] == 1
    assert ax["silently_unaccounted"] == 0, ax
    assert ax["refused_loud"] + ax["lifted_cited"] == 1, ax
    # Prefer refuse when For is still a gap (instrument engaged).
    fas = rpc.get("factoryAuditSummary") or {}
    if int((fas.get("statusCounts") or {}).get("unresolved") or 0) > 0:
        assert ax["refused_loud"] == 1


def test_implemented_diggable_assert_lifts() -> None:
    src = (
        "def claimed():\n"
        "    return 1\n"
        "def test_claimed():\n"
        "    assert claimed() == 1\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["lifted_cited"] == 1
    assert ax["silently_unaccounted"] == 0
    assert ax["refused_loud"] == 0
