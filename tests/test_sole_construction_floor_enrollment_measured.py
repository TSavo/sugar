"""Teeth: enrollment mint must not bank crash as measured residual."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "sole_construction_floor_enrollment",
    ROOT / "tools" / "sole_construction_floor_enrollment.py",
)
assert _SPEC is not None and _SPEC.loader is not None
ENR = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ENR
_SPEC.loader.exec_module(ENR)


def test_crash_before_scan_mints_unmeasured_not_completed() -> None:
    """Plant infrastructure death (exit 2): body must be UNMEASURED, not residual."""
    report = ENR.mint_axis_report(
        axis_id="silent",
        display="R_silent",
        commit_sha="deadbeef",
        exit_code=2,
        kind="process",
        unmeasured_reason="planted auth/init failure",
    )
    assert report["measured"] is False
    assert report["status"] == "unmeasured"
    assert report["floorExitGreen"] is False
    assert report["unmeasuredReason"]
    assert "auth" in report["unmeasuredReason"].lower() or "planted" in report["unmeasuredReason"].lower()
    # Must not look like a measured residual red (status=completed measured=True exit=1).
    assert report["status"] != "completed"
    assert report.get("totals", {}).get("unmeasured") == 1


def test_genuine_nonzero_residual_is_measured_not_unmeasured() -> None:
    """Plant residual red (exit 1 after completed scan): measured with residual."""
    report = ENR.mint_axis_report(
        axis_id="native-crash",
        display="R_native_crashes",
        commit_sha="deadbeef",
        exit_code=1,
        kind="process",
    )
    assert report["measured"] is True
    assert report["status"] == "completed"
    assert report["floorExitGreen"] is False
    assert report["exitCode"] == 1
    assert report.get("unmeasuredReason") is None


def test_green_residual_is_measured() -> None:
    report = ENR.mint_axis_report(
        axis_id="timeout",
        display="R_timeouts",
        commit_sha="deadbeef",
        exit_code=0,
        kind="process",
    )
    assert report["measured"] is True
    assert report["status"] == "completed"
    assert report["floorExitGreen"] is True


def test_crash_and_residual_never_look_alike() -> None:
    crash = ENR.mint_axis_report(
        axis_id="bare-exception",
        display="R_bare_exceptions",
        commit_sha="c",
        exit_code=2,
        kind="process",
    )
    residual = ENR.mint_axis_report(
        axis_id="bare-exception",
        display="R_bare_exceptions",
        commit_sha="c",
        exit_code=1,
        kind="process",
    )
    # The distinction enrollment exists to make:
    assert (crash["measured"], crash["status"]) != (residual["measured"], residual["status"])
    assert crash["measured"] is False and residual["measured"] is True


def test_enrollment_roll_call_unmeasured_not_residual_red(tmp_path: Path) -> None:
    """UNMEASURED axis fails completeness; must not be counted as residualRed."""
    # Four axes measured green; silent is crash-unmeasured.
    for axis in ENR.ENROLLED:
        if axis.axis_id == "silent":
            report = ENR.mint_axis_report(
                axis_id=axis.axis_id,
                display=axis.display,
                commit_sha="tip",
                exit_code=2,
                kind=axis.kind,
                unmeasured_reason="planted crash before measurement",
            )
        else:
            report = ENR.mint_axis_report(
                axis_id=axis.axis_id,
                display=axis.display,
                commit_sha="tip",
                exit_code=0,
                kind=axis.kind,
            )
        path = tmp_path / f"floor-axis-{axis.axis_id}" / ENR.REPORT_FILENAME
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(report), encoding="utf-8")
    code, summary = ENR.check_attendance(tmp_path, require_commit="tip")
    assert code == 1
    assert summary["status"] == "UNMEASURED"
    assert "silent" in summary["unresolved"]
    assert "silent" not in summary["residualRed"]
    assert "silent" not in summary["attended"]
