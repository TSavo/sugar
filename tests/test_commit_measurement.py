"""Construction-door teeth for CommitMeasurement (CI path; no local agent pytest)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CM = _load("commit_measurement", "tools/commit_measurement.py")
GATE = _load("commit_measurement_gate", "tools/commit_measurement_gate.py")


def _body(failed: int = 3, collected: int = 12) -> dict:
    return {"totals": {"failed": failed, "collected": collected}}


def test_scoreboard_authority_false() -> None:
    assert CM.SCOREBOARD_AUTHORITY is False


def test_measured_refuses_without_parsed_body() -> None:
    """Lying twin of lease-only success: no body => not Measured."""
    with pytest.raises(CM.CommitMeasurementError, match="parsed body|NoReport"):
        CM.measured(
            3,
            receipt_cid="blake3-512:abc",
            body=None,  # type: ignore[arg-type]
            value_field_path="totals.failed",
            exit_code=1,
        )


def test_measured_refuses_value_not_from_body() -> None:
    with pytest.raises(CM.CommitMeasurementError, match="does not match body"):
        CM.measured(
            99,
            receipt_cid="lease:1",
            body=_body(failed=3),
            value_field_path="totals.failed",
            exit_code=1,
        )


def test_measured_refuses_missing_body_field() -> None:
    with pytest.raises(CM.CommitMeasurementError, match="missing value field|NoReport"):
        CM.measured(
            0,
            receipt_cid="lease:1",
            body={"totals": {}},
            value_field_path="totals.failed",
            exit_code=0,
        )


def test_direct_measured_without_seal_refuses() -> None:
    with pytest.raises(CM.CommitMeasurementError, match="sealed"):
        CM.Measured(3, "lease", "body-cid", "totals.failed", 12, 1, object())


def test_measured_from_body_ok() -> None:
    body = _body(3, 12)
    m = CM.measured(
        3,
        receipt_cid="lease:1",
        body=body,
        value_field_path="totals.failed",
        exit_code=1,
    )
    assert m.value == 3
    assert m.collected == 12
    assert m.body_artifact_cid == CM.content_cid(body)
    assert m.receipt_cid == "lease:1"


def test_receipt_ok_missing_body_is_unmeasured_noreport(tmp_path: Path) -> None:
    """THE twin: valid lease, no suite-report.json → Unmeasured(NoReport)."""
    lease = {
        "schemaVersion": 1,
        "leaseClass": "python-package-suite",
        "acquired": True,
        "measurementStatus": "completed/findings",
        "commit": "deadbeef",
    }
    (tmp_path / "lease-only.json").write_text(json.dumps(lease), encoding="utf-8")
    v = CM.compose_tip_from_receipts_dir("deadbeef", tmp_path)
    assert isinstance(v, CM.PartialVector)
    axis = v.axes["python-package-suite"]
    assert isinstance(axis, CM.Unmeasured)
    assert "NoReport" in axis.reason
    assert not hasattr(CM.PartialVector, "total")


def test_receipt_ok_unparseable_body_is_unmeasured(tmp_path: Path) -> None:
    lease = {
        "schemaVersion": 1,
        "leaseClass": "python-package-suite",
        "acquired": True,
        "measurementStatus": "completed/findings",
        "commit": "deadbeef",
    }
    (tmp_path / "lease.json").write_text(json.dumps(lease), encoding="utf-8")
    (tmp_path / "suite-report.json").write_text("not-json{{{", encoding="utf-8")
    v = CM.compose_tip_from_receipts_dir("deadbeef", tmp_path)
    assert isinstance(v, CM.PartialVector)
    assert isinstance(v.axes["python-package-suite"], CM.Unmeasured)


def test_sealed_pair_lease_not_acquired() -> None:
    r = CM.measured_from_sealed_pair(
        commit_sha="abc",
        lease_record={"acquired": False, "leaseClass": "python-package-suite"},
        lease_receipt_cid="lease:1",
        body=_body(),
        body_artifact_cid=CM.content_cid(_body()),
        value_field_path="totals.failed",
    )
    assert isinstance(r, CM.Unmeasured)


def test_unmeasured_is_third_value_not_zero() -> None:
    u = CM.unmeasured("never ran")
    m = CM.measured(
        0,
        receipt_cid="l",
        body=_body(0, 1),
        value_field_path="totals.failed",
        exit_code=0,
    )
    assert type(u) is not type(m)
    assert m.value == 0


def test_complete_has_total_partial_does_not() -> None:
    complete = CM.commit_measurement(
        "sha",
        "roster:tip",
        {
            "a": CM.measured(
                1,
                receipt_cid="l1",
                body=_body(1, 2),
                value_field_path="totals.failed",
                exit_code=1,
            ),
            "b": CM.measured(
                2,
                receipt_cid="l2",
                body=_body(2, 2),
                value_field_path="totals.failed",
                exit_code=1,
            ),
        },
    )
    assert isinstance(complete, CM.CompleteVector)
    assert complete.total == 3
    partial = CM.commit_measurement(
        "sha",
        "roster:tip",
        {
            "a": CM.measured(
                1,
                receipt_cid="l1",
                body=_body(1, 2),
                value_field_path="totals.failed",
                exit_code=1,
            ),
            "b": CM.unmeasured("NoReport: missing body"),
        },
    )
    assert isinstance(partial, CM.PartialVector)
    with pytest.raises(AttributeError):
        _ = partial.total  # type: ignore[attr-defined]
    assert "total" not in partial.to_json()


def test_forbidden_board_axis_names() -> None:
    with pytest.raises(CM.CommitMeasurementError, match="corpus-board"):
        CM.commit_measurement(
            "sha",
            "roster",
            {"R_construction": CM.unmeasured("no")},
        )


def test_gate_required_not_advisory(tmp_path: Path) -> None:
    assert GATE.main(["--composition", str(tmp_path / "gone.json"), "--require-complete"]) == 1
    partial = CM.commit_measurement(
        "sha", "roster", {"a": CM.unmeasured("NoReport")}
    )
    p = tmp_path / "cm.json"
    p.write_text(json.dumps(partial.to_json()), encoding="utf-8")
    assert GATE.main(["--composition", str(p), "--require-complete"]) == 1
    complete = CM.commit_measurement(
        "sha",
        "roster",
        {
            "a": CM.measured(
                0,
                receipt_cid="l",
                body=_body(0, 1),
                value_field_path="totals.failed",
                exit_code=0,
            )
        },
    )
    p.write_text(json.dumps(complete.to_json()), encoding="utf-8")
    assert GATE.main(["--composition", str(p), "--require-complete"]) == 0


def test_attendance_workflow_enrolls_compose_and_gate() -> None:
    """Enrollment is existence: CI must require the object."""
    text = (ROOT / ".github/workflows/heavy-measurement-attendance.yml").read_text(
        encoding="utf-8"
    )
    assert "commit_measurement" in text
    assert "commit_measurement_gate.py" in text
    assert "--require-complete" in text
    assert "commit-measurement.json" in text
