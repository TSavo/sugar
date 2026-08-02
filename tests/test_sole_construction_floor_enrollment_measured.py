"""Teeth: enrollment mint residual magnitude from floor summary, not exit invent."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "sole_construction_floor_enrollment",
    ROOT / "tools" / "sole_construction_floor_enrollment.py",
)
assert _SPEC is not None and _SPEC.loader is not None
ENR = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ENR
_SPEC.loader.exec_module(ENR)


def _seat(base: str, shard: int = 0) -> str:
    return f"{base}-s{shard:02d}"


def test_crash_before_scan_mints_unmeasured_not_completed() -> None:
    """Plant infrastructure death (exit 2): body must be UNMEASURED, not residual."""
    report = ENR.mint_axis_report(
        axis_id=_seat("silent"),
        display="R_silent[s00]",
        commit_sha="deadbeef",
        exit_code=2,
        kind="process",
        unmeasured_reason="planted auth/init failure",
    )
    assert report["measured"] is False
    assert report["status"] == "unmeasured"
    assert report["floorExitGreen"] is False
    assert report["unmeasuredReason"]
    assert "auth" in report["unmeasuredReason"].lower() or "planted" in report[
        "unmeasuredReason"
    ].lower()
    assert report["status"] != "completed"
    assert report.get("totals", {}).get("unmeasured") == 1
    assert report.get("residualCount") is None


def test_genuine_nonzero_residual_requires_count_not_exit_invent() -> None:
    """Measured residual must carry magnitude from floor summary — not exit=1 invent."""
    with pytest.raises(ValueError, match="residual_count|floor summary|invent"):
        ENR.mint_axis_report(
            axis_id=_seat("native-crash"),
            display="R_native_crashes[s00]",
            commit_sha="deadbeef",
            exit_code=1,
            kind="process",
        )
    report = ENR.mint_axis_report(
        axis_id=_seat("native-crash"),
        display="R_native_crashes[s00]",
        commit_sha="deadbeef",
        exit_code=1,
        kind="process",
        residual_count=47,
        residual_source="floor-summary.json",
        residual_key="R_native_crashes",
    )
    assert report["measured"] is True
    assert report["status"] == "completed"
    assert report["floorExitGreen"] is False
    assert report["exitCode"] == 1
    assert report["residualCount"] == 47
    assert report["totals"]["failed"] == 47
    assert report["totals"]["residual"] == 47
    assert report.get("unmeasuredReason") is None


def test_green_residual_is_measured_with_zero_count() -> None:
    report = ENR.mint_axis_report(
        axis_id=_seat("timeout"),
        display="R_timeouts[s00]",
        commit_sha="deadbeef",
        exit_code=0,
        kind="process",
        residual_count=0,
        residual_source="floor-summary.json",
    )
    assert report["measured"] is True
    assert report["status"] == "completed"
    assert report["floorExitGreen"] is True
    assert report["residualCount"] == 0
    assert report["totals"]["failed"] == 0


def test_load_residual_from_pandas_floor_summary(tmp_path: Path) -> None:
    summary = {
        "kind": "pandas-floor-summary-v1",
        "floor": "native-crash",
        "totals": {"R_native_crashes": 12, "completed": 100},
    }
    path = tmp_path / "floor-summary.json"
    path.write_text(json.dumps(summary), encoding="utf-8")
    assert (
        ENR.load_residual_count_from_floor_summary(
            path, residual_key="R_native_crashes"
        )
        == 12
    )


def test_load_residual_from_floor_residual_v1(tmp_path: Path) -> None:
    path = tmp_path / "static.json"
    path.write_text(
        json.dumps(
            {
                "kind": "floor-residual-v1",
                "residualKey": "R_static_sole_construction",
                "residualCount": 3,
            }
        ),
        encoding="utf-8",
    )
    assert (
        ENR.load_residual_count_from_floor_summary(
            path, residual_key="R_static_sole_construction"
        )
        == 3
    )


def test_crash_and_residual_never_look_alike() -> None:
    crash = ENR.mint_axis_report(
        axis_id=_seat("bare-exception"),
        display="R_bare_exceptions[s00]",
        commit_sha="c",
        exit_code=2,
        kind="process",
    )
    residual = ENR.mint_axis_report(
        axis_id=_seat("bare-exception"),
        display="R_bare_exceptions[s00]",
        commit_sha="c",
        exit_code=1,
        kind="process",
        residual_count=9,
    )
    assert (crash["measured"], crash["status"]) != (
        residual["measured"],
        residual["status"],
    )
    assert crash["measured"] is False and residual["measured"] is True
    assert residual["residualCount"] == 9
    assert residual["totals"]["failed"] == 9


def test_enrollment_roll_call_unmeasured_not_residual_red(tmp_path: Path) -> None:
    """UNMEASURED axis fails completeness; must not be counted as residualRed."""
    for axis in ENR.ENROLLED:
        if axis.axis_id == _seat("silent") or axis.axis_id.startswith("silent-"):
            if axis.axis_id != _seat("silent"):
                # only plant unmeasured on silent-s00; other silent seats green
                report = ENR.mint_axis_report(
                    axis_id=axis.axis_id,
                    display=axis.display,
                    commit_sha="tip",
                    exit_code=0,
                    kind=axis.kind,
                    residual_count=0,
                )
            else:
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
                residual_count=0,
            )
        path = tmp_path / f"floor-axis-{axis.axis_id}" / ENR.REPORT_FILENAME
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(report), encoding="utf-8")
    code, summary = ENR.check_attendance(tmp_path, require_commit="tip")
    assert code == 1
    assert summary["status"] == "UNMEASURED"
    assert _seat("silent") in summary["unresolved"]
    assert _seat("silent") not in summary["residualRed"]
    assert _seat("silent") not in summary["attended"]


def test_residual_magnitude_drives_residual_red_not_exit_alone(
    tmp_path: Path,
) -> None:
    """residualCount>0 is residual red even if someone mints exit=0 wrongly."""
    for axis in ENR.ENROLLED:
        if axis.axis_id == _seat("native-crash"):
            report = ENR.mint_axis_report(
                axis_id=axis.axis_id,
                display=axis.display,
                commit_sha="tip",
                exit_code=0,  # exit lies; magnitude is authority
                kind=axis.kind,
                residual_count=5,
            )
        else:
            report = ENR.mint_axis_report(
                axis_id=axis.axis_id,
                display=axis.display,
                commit_sha="tip",
                exit_code=0,
                kind=axis.kind,
                residual_count=0,
            )
        path = tmp_path / f"floor-axis-{axis.axis_id}" / ENR.REPORT_FILENAME
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(report), encoding="utf-8")
    code, summary = ENR.check_attendance(tmp_path, require_commit="tip")
    assert code == 0
    assert summary["status"] == "complete"
    assert _seat("native-crash") in summary["residualRed"]
