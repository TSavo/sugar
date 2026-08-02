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


def test_scoreboard_authority_false() -> None:
    assert CM.SCOREBOARD_AUTHORITY is False


def test_measured_requires_lease_and_body_cids() -> None:
    with pytest.raises(CM.CommitMeasurementError, match="receipt_cid"):
        CM.Measured(0, "", "body", "totals.failed", 1, 0)
    with pytest.raises(CM.CommitMeasurementError, match="body_artifact_cid"):
        CM.Measured(0, "lease", "", "totals.failed", 1, 0)
    with pytest.raises(CM.CommitMeasurementError, match="value_field_path"):
        CM.Measured(0, "lease", "body", "", 1, 0)


def test_measured_from_sealed_pair_unmeasured_without_body_field() -> None:
    reading = CM.measured_from_sealed_pair(
        commit_sha="abc",
        lease_record={"acquired": True, "leaseClass": "python-sole-construction-floors"},
        lease_receipt_cid="lease:1",
        body={"totals": {}},
        body_artifact_cid="body:1",
        value_field_path="totals.failed",
    )
    assert isinstance(reading, CM.Unmeasured)


def test_measured_from_sealed_pair_unmeasured_when_lease_not_acquired() -> None:
    reading = CM.measured_from_sealed_pair(
        commit_sha="abc",
        lease_record={"acquired": False, "leaseClass": "python-sole-construction-floors"},
        lease_receipt_cid="lease:1",
        body={"totals": {"failed": 0, "collected": 3}},
        body_artifact_cid="body:1",
        value_field_path="totals.failed",
    )
    assert isinstance(reading, CM.Unmeasured)
    assert "not acquired" in reading.reason


def test_measured_from_sealed_pair_cites_body_value() -> None:
    body = {"totals": {"failed": 7, "collected": 40}}
    reading = CM.measured_from_sealed_pair(
        commit_sha="abc",
        lease_record={
            "acquired": True,
            "leaseClass": "python-sole-construction-floors",
            "measurementStatus": "completed/findings",
        },
        lease_receipt_cid="lease:1",
        body=body,
        body_artifact_cid=CM.content_cid(body),
        value_field_path="totals.failed",
        collected_field_path="totals.collected",
    )
    assert isinstance(reading, CM.Measured)
    assert reading.value == 7
    assert reading.collected == 40
    assert reading.body_artifact_cid.startswith("blake2b-256:")


def test_unmeasured_is_third_value_not_zero() -> None:
    u = CM.unmeasured("never ran")
    m = CM.measured(
        0,
        receipt_cid="l",
        body_artifact_cid="b",
        value_field_path="totals.failed",
        collected=1,
        exit_code=0,
    )
    assert type(u) is not type(m)
    assert m.value == 0
    assert not u.is_measured()


def test_complete_has_total_partial_does_not() -> None:
    complete = CM.commit_measurement(
        "sha",
        "roster:tip",
        {
            "a": CM.measured(
                1,
                receipt_cid="l1",
                body_artifact_cid="b1",
                value_field_path="totals.failed",
                collected=2,
                exit_code=1,
            ),
            "b": CM.measured(
                2,
                receipt_cid="l2",
                body_artifact_cid="b2",
                value_field_path="totals.failed",
                collected=2,
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
                body_artifact_cid="b1",
                value_field_path="totals.failed",
                collected=2,
                exit_code=1,
            ),
            "b": CM.unmeasured("missing body"),
        },
    )
    assert isinstance(partial, CM.PartialVector)
    assert not hasattr(CM.PartialVector, "total")
    with pytest.raises(AttributeError):
        _ = partial.total  # type: ignore[attr-defined]
    assert "total" not in partial.to_json()


def test_forbidden_board_axis_names() -> None:
    with pytest.raises(CM.CommitMeasurementError, match="corpus-board"):
        CM.commit_measurement(
            "sha",
            "roster",
            {
                "R_construction": CM.unmeasured("no"),
            },
        )


def test_compose_tip_lease_without_body_is_unmeasured(tmp_path: Path) -> None:
    lease = {
        "schemaVersion": 1,
        "leaseClass": "python-sole-construction-floors",
        "acquired": True,
        "measurementStatus": "completed/findings",
        "commit": "deadbeef",
    }
    (tmp_path / "lease.json").write_text(json.dumps(lease), encoding="utf-8")
    v = CM.compose_tip_from_receipts_dir("deadbeef", tmp_path)
    assert isinstance(v, CM.PartialVector)
    assert "python-sole-construction-floors" in v.unmeasured_axes()
    assert "body artifact" in v.axes["python-sole-construction-floors"].reason


def test_compose_tip_lease_plus_body_is_measured(tmp_path: Path) -> None:
    body = {
        "totals": {"failed": 4, "collected": 20},
        "failedNodeIds": ["a", "b", "c", "d"],
        "gitCommit": "deadbeef",
    }
    lease = {
        "schemaVersion": 1,
        "leaseClass": "python-sole-construction-floors",
        "acquired": True,
        "measurementStatus": "completed/findings",
        "commit": "deadbeef",
        "leaseRecord": None,
    }
    # embed lease + body in one report style object
    suite = {**body, "leaseRecord": lease}
    (tmp_path / "floor-report.json").write_text(json.dumps(suite), encoding="utf-8")
    v = CM.compose_tip_from_receipts_dir("deadbeef", tmp_path)
    assert isinstance(v, CM.CompleteVector) or isinstance(v, CM.PartialVector)
    assert isinstance(v.axes["python-sole-construction-floors"], CM.Measured)
    assert v.axes["python-sole-construction-floors"].value == 4


def test_gate_missing_composition_is_red(tmp_path: Path) -> None:
    assert GATE.main(["--composition", str(tmp_path / "nope.json"), "--require-complete"]) == 1


def test_gate_partial_require_complete_is_red(tmp_path: Path) -> None:
    v = CM.commit_measurement(
        "sha",
        "roster",
        {"a": CM.unmeasured("gone")},
    )
    path = tmp_path / "cm.json"
    path.write_text(json.dumps(v.to_json()), encoding="utf-8")
    assert GATE.main(["--composition", str(path), "--require-complete"]) == 1


def test_gate_complete_require_complete_is_green(tmp_path: Path) -> None:
    v = CM.commit_measurement(
        "sha",
        "roster",
        {
            "a": CM.measured(
                0,
                receipt_cid="l",
                body_artifact_cid="b",
                value_field_path="totals.failed",
                collected=1,
                exit_code=0,
            )
        },
    )
    path = tmp_path / "cm.json"
    path.write_text(json.dumps(v.to_json()), encoding="utf-8")
    assert GATE.main(["--composition", str(path), "--require-complete"]) == 0


def test_empty_receipts_tip_produces_partial_and_gate_red(tmp_path: Path) -> None:
    """LIVE twin: tip with NO receipts → PartialVector → gate exit 1 (not skip).

    This is the case that proves the object is required: silence is Unmeasured
    on every tip axis, composition exists as partial, and --require-complete
    is red. A gate that only fires when instruments already succeeded is not
    a gate.
    """
    empty = tmp_path / "receipts"
    empty.mkdir()
    vector = CM.compose_tip_from_receipts_dir("tip-with-zero-receipts", empty)
    assert isinstance(vector, CM.PartialVector), (
        f"empty receipts must be PartialVector, got {type(vector).__name__}"
    )
    assert vector.unmeasured_axes(), "every tip axis should be Unmeasured"
    assert "total" not in vector.to_json()
    composition = tmp_path / "commit-measurement.json"
    composition.write_text(
        __import__("json").dumps(vector.to_json()), encoding="utf-8"
    )
    code = GATE.main(
        ["--composition", str(composition), "--require-complete"]
    )
    assert code == 1, f"gate must RED on empty-receipt tip, got exit {code}"


def test_missing_composition_file_gate_red_not_skipped(tmp_path: Path) -> None:
    """Absent CommitMeasurement artifact is RED, never 'no file = fine'."""
    code = GATE.main(
        ["--composition", str(tmp_path / "commit-measurement.json"), "--require-complete"]
    )
    assert code == 1


def test_workflow_runs_gate_even_when_attendance_would_exit_red() -> None:
    """Enrollment law: compose+gate must not sit behind set -e on attendance.

    Re-derived from the workflow file (live instrument path), not a hand list.
    """
    text = (
        ROOT / ".github/workflows/heavy-measurement-attendance.yml"
    ).read_text(encoding="utf-8")
    assert "commit_measurement_gate.py" in text
    assert "--require-complete" in text
    # Must capture attendance exit and still run gate (not set -e abort before compose)
    assert "gate_exit" in text or "GATE" in text or "att_exit" in text
    assert "compose_tip_from_receipts_dir" in text or "commit_measurement.py" in text
    # Decorative pattern: separate gate step after roll call under set -e only
    # would skip on attendance red. The fixed job uses att_exit/gate_exit OR.
    assert "att_exit" in text and "gate_exit" in text


def test_s03_compose_cli_allows_partial_exit_zero(tmp_path: Path) -> None:
    """S0.3 packaging: empty/partial receipts still write PartialVector exit 0.

    --require-complete is attendance tip-complete claim only — not S0.3.
    """
    import subprocess
    import sys

    empty = tmp_path / "receipts"
    empty.mkdir()
    out = tmp_path / "commit-measurement.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "compose_commit_measurement.py"),
            "--commit",
            "s03-tip",
            "--receipts-dir",
            str(empty),
            "--output",
            str(out),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert out.is_file()
    payload = __import__("json").loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "partial"
    assert "total" not in payload
    assert payload["unmeasuredAxes"]
