# SPDX-License-Identifier: MIT OR Apache-2.0
"""R_source_audit_cid_alone_presence — auditor for SIN CLUSTER 7 residual class.

The product door keys presence by full roll-call identity. This instrument
keeps the *class* of CID-alone status producers red if it returns: historical
shapes trip the scanner; the production one-door shape stays clean; live
``src/`` packages measure R=0.

Ladder note: auditor (not type) because free Python can re-derive the wire
dict. Retirement: typed partition constructors that only accept full-tuple
present keys — then delete this file.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "source_audit_presence_identity_law.py"
_SPEC = importlib.util.spec_from_file_location(
    "source_audit_presence_identity_law", _SCANNER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _SCANNER
_SPEC.loader.exec_module(_SCANNER)


def _offenders(source: str):
    return _SCANNER.offenders_in_source(source, path="<twin>")


def test_historical_lift_rpc_cid_alone_is_caught() -> None:
    """Lying twin: the dual-producer shape that inflated warranted."""
    found = _offenders(_SCANNER.HISTORICAL_LIFT_RPC_CID_ALONE)
    kinds = {o.kind for o in found}
    assert "present-cids-set" in kinds or "present-cid-setcomp" in kinds, found
    assert "status-by-cid-membership" in kinds, found


def test_historical_tree_enumerate_cid_alone_is_caught() -> None:
    found = _offenders(_SCANNER.HISTORICAL_TREE_ENUMERATE_CID_ALONE)
    kinds = {o.kind for o in found}
    assert "present-cids-set" in kinds or "present-cid-setcomp" in kinds, found
    assert "status-by-cid-membership" in kinds, found


def test_production_one_door_is_clean() -> None:
    assert _offenders(_SCANNER.PRODUCTION_ONE_DOOR) == []


def test_live_production_src_holds_at_zero() -> None:
    """Zero is measured, not inferred. Planted historical shape still trips."""
    offenders, unreadable = _SCANNER.scan_roots([_KIT])
    assert unreadable == [], unreadable
    assert offenders == [], [o.to_json() for o in offenders]


def test_planted_offender_trips_live_scan(tmp_path: Path) -> None:
    """Lying twin against the live scan path: insert the historical shape."""
    src = tmp_path / "src" / "planted_pkg"
    src.mkdir(parents=True)
    (src / "bad.py").write_text(
        _SCANNER.HISTORICAL_LIFT_RPC_CID_ALONE, encoding="utf-8"
    )
    offenders, unreadable = _SCANNER.scan_roots([tmp_path])
    assert unreadable == []
    assert len(offenders) >= 1, "planted CID-alone producer must be red"
    assert any(o.kind == "status-by-cid-membership" for o in offenders)


def test_scanner_self_test_passes() -> None:
    assert _SCANNER.self_test() == 0


# ---------------------------------------------------------------------------
# Conservation tooth — plant the illegal ledger; status-only sum stays green
# ---------------------------------------------------------------------------


def test_ledger_tooth_fires_on_historical_mixed_keying() -> None:
    """THE tooth that must fail under old lift_rpc totals.

    warranted=2 (CID-alone status), report.R=1 (absent seat), source_loci=2.
    Status-only conservation (warranted + unresolved_from_status) would see
    unresolved=0 and pass 2+0==2 — decorative. The live tooth uses report.R.
    """
    from sugar_lift_py_tests.tree_enumerate import assert_source_audit_ledger

    with pytest.raises(AssertionError, match="report.R"):
        assert_source_audit_ledger(
            warranted=2,
            unresolved=0,
            source_loci=2,
            report_R=1,
        )


def test_ledger_tooth_status_only_sum_is_not_sufficient() -> None:
    """Prove the deleted shell cannot be the instrument: 2+0==2 is green."""
    warranted, unresolved, source_loci = 2, 0, 2
    # Decorative form — green under the illegal state:
    assert warranted + unresolved == source_loci
    # Live form — red under the same numbers:
    from sugar_lift_py_tests.tree_enumerate import assert_source_audit_ledger

    with pytest.raises(AssertionError):
        assert_source_audit_ledger(
            warranted=warranted,
            unresolved=unresolved,
            source_loci=source_loci,
            report_R=1,
        )


def test_ledger_tooth_quiet_when_partition_honest() -> None:
    from sugar_lift_py_tests.tree_enumerate import assert_source_audit_ledger

    assert_source_audit_ledger(
        warranted=1, unresolved=1, source_loci=2, report_R=1
    )
    assert_source_audit_ledger(
        warranted=2, unresolved=0, source_loci=2, report_R=0
    )
    assert_source_audit_ledger(
        warranted=0, unresolved=2, source_loci=2, report_R=2
    )


def test_lift_rpc_calls_the_one_door_not_cid_alone() -> None:
    """Product path: _roll_call_audit_leaf must not re-derive presence by CID."""
    import inspect

    from sugar_lift_py_tests import lift_rpc

    src = inspect.getsource(lift_rpc._roll_call_audit_leaf)
    assert "source_audit_from_report" in src
    body = src.split('"""', 2)[-1] if '"""' in src else src
    assert "present_cids" not in body
    assert "entry.cid in" not in body
