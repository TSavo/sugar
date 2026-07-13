"""Assertion axis projects the collapse's fact rows -- not pre-rebuild audits.

A census assert is LIFTED+CITED when a kind=contract ::assertion row's warrant
memento covers that file:line. Refused-loud comes from auditOnlyGaps whose
site matches the locus. Silently-unaccounted is the Crime-1 gate (RED when >0).
"""

from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload

# Minority demo (enc + test_enc): the FALSE-RED case that #4084 fact rows fix.
_MINORITY_DEMO = (
    "def enc(x):\n"
    '    if x == "ccc":\n'
    '        return "yyy"\n'
    "    return x\n"
    "\n"
    "def test_enc():\n"
    '    assert enc("ccc") == "yyy"\n'
)


def _coverage(source: str, *, file: str = "vendor.py", payload_rpc=None):
    if payload_rpc is None:
        payload_rpc = lift_file_payload(source, file).to_rpc()
    disk = census_source(source, file=file)
    return account_lift_coverage(disk, payload_rpc)


def test_minority_demo_assert_is_lifted_cited_not_silent_residue() -> None:
    """(a) Live false-red case: stated=1, lifted_cited=1, silently_unaccounted=0."""
    cov = _coverage(_MINORITY_DEMO, file="vendor.py")
    ax = cov.assertions.to_json()
    assert ax["stated"] == 1
    assert ax["lifted_cited"] == 1
    assert ax["refused_loud"] == 0
    assert ax["silently_unaccounted"] == 0
    assert ax["is_zero"] is True
    assert ax["silent_loci"] == []
    lifted = ax["lifted_loci"]
    assert len(lifted) == 1
    assert lifted[0]["file"] == "vendor.py"
    assert lifted[0]["line"] == 7


def test_unliftable_assert_refused_loud_via_audit_door() -> None:
    """(b) Report path holds per-def; audit gaps refuse the assert locus.

    Finding (wiring, post report-renders-None-arm-red):
      * lift_file_payload holds FactoryPanic (hold_panic=True) and projects a
        FactoryWalkRedRowDto -- the visual None arm. Nothing raises.
      * audit_lift_file still returns structured AuditOnlyGap rows; the wall
        audit-only path drinks them as auditOnlyGaps. Coverage refused-loud
        matches gap site (blame file:line) to the census AssertLocus.
      * Unliftable construct *on* the assert expression (ListComp) puts blame
        on the same line as the census assert -- that is the refused-loud join.
    """
    # Unliftable expression *on* the assert line so gap site == assert locus.
    source = "def test_t():\n    assert [x for x in [1]]\n"
    file = "t.py"

    # Report path holds: red walk row, no raise.
    held = lift_file_payload(source, file)
    assert not any(row.name.endswith("::assertion") for row in held.ir)
    from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import FactoryWalkRedRowDto

    red = [r for r in held.factory_walk if isinstance(r, FactoryWalkRedRowDto)]
    assert red and red[0].ast_kind == "ListComp"

    payload, gaps = audit_lift_file(source, file, hold_panic=True)
    assert gaps, "audit door must enumerate the ListComp gap"
    assert gaps[0].info.get("observed") == "ListComp"
    assert gaps[0].info.get("blame", "").startswith(f"{file}:2:")

    rpc = payload.to_rpc()
    rpc["auditOnlyGaps"] = [gap.to_json() for gap in gaps]
    # No ::assertion fact row -- the testimony def never completed.
    assert not any(
        (row.get("name") or "").endswith("::assertion")
        for row in (rpc.get("ir") or [])
        if isinstance(row, dict)
    )

    cov = _coverage(source, file=file, payload_rpc=rpc)
    ax = cov.assertions.to_json()
    assert ax["stated"] == 1
    assert ax["lifted_cited"] == 0
    assert ax["refused_loud"] == 1
    assert ax["silently_unaccounted"] == 0
    assert ax["is_zero"] is True
    assert ax["refused_loci"][0]["line"] == 2


def test_while_before_assert_gap_site_is_while_not_assert() -> None:
    """While before an assert: report holds; gap site is While, assert silent.

    Audit gap site is the While line, not the Assert -- site-matched
    refused-loud does not claim the assert. Crime-1 stays RED for that
    locus unless a fact row or a gap on the assert line appears.
    """
    source = (
        "def bad(x):\n" "    while x:\n" "        x = x - 1\n" "    assert x == 0\n"
    )
    # Report path holds the While gap as a red factory_walk row.
    held = lift_file_payload(source, "bad.py")
    from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import FactoryWalkRedRowDto

    red = [r for r in held.factory_walk if isinstance(r, FactoryWalkRedRowDto)]
    assert red and red[0].ast_kind == "While"

    payload, gaps = audit_lift_file(source, "bad.py", hold_panic=True)
    assert any(g.info.get("observed") == "While" for g in gaps)
    rpc = payload.to_rpc()
    rpc["auditOnlyGaps"] = [gap.to_json() for gap in gaps]
    cov = _coverage(source, file="bad.py", payload_rpc=rpc)
    # Assert line 4 has neither a ::assertion warrant nor a gap site -- silent.
    assert cov.assertions.stated == 1
    assert cov.assertions.silently_unaccounted == 1
    assert cov.assertions.silent_loci[0]["line"] == 4
