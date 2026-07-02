# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import subprocess

from sugar_lift_py_tests import verifier


def _completed(stdout: str, *, stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["/fake/sugar"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _stub_sugar_cli(monkeypatch, completed) -> None:
    monkeypatch.setattr(verifier, "find_sugar_cli", lambda: "/fake/sugar")

    def fake_run(cmd, *, capture_output, text, check):
        assert cmd[0] == "/fake/sugar"
        assert capture_output is True
        assert text is True
        assert check is False
        return completed

    monkeypatch.setattr(verifier.subprocess, "run", fake_run)


def _assert_protocol_drift_report(report) -> None:
    assert report.success is False
    assert (
        report.tier1_discharge_fraction,
        report.tier2_discharge_fraction,
        report.tier3_remaining,
    ) != (1.0, 1.0, 0)
    assert report.violations
    detail = "\n".join([report.summary, *report.violations]).lower()
    assert "malformed" in detail
    assert "json" in detail
    assert "protocol drift" in detail
    assert "not json" in detail


def test_verify_project_reports_malformed_cli_json_as_failure(monkeypatch) -> None:
    _stub_sugar_cli(monkeypatch, _completed("not json"))

    report = verifier.verify_project("/tmp/project")

    _assert_protocol_drift_report(report)


def test_prove_contract_reports_malformed_cli_json_as_failure(monkeypatch) -> None:
    _stub_sugar_cli(monkeypatch, _completed("not json"))

    report = verifier.prove_contract("/tmp/project/contract.json")

    _assert_protocol_drift_report(report)


def test_verify_project_accepts_valid_cli_json_report(monkeypatch) -> None:
    _stub_sugar_cli(
        monkeypatch,
        _completed(
            json.dumps(
                {
                    "success": True,
                    "tier1_discharge_fraction": 1.0,
                    "tier2_discharge_fraction": 0.75,
                    "tier3_remaining": 2,
                    "violations": [],
                    "summary": "verification passed",
                }
            )
        ),
    )

    report = verifier.verify_project("/tmp/project")

    assert report.success is True
    assert report.tier1_discharge_fraction == 1.0
    assert report.tier2_discharge_fraction == 0.75
    assert report.tier3_remaining == 2
    assert report.violations == []
    assert report.summary == "verification passed"


def test_prove_contract_accepts_valid_cli_json_report(monkeypatch) -> None:
    _stub_sugar_cli(
        monkeypatch,
        _completed(
            json.dumps(
                {
                    "success": True,
                    "tier1_discharge_fraction": 0.5,
                    "tier2_discharge_fraction": 1.0,
                    "tier3_remaining": 1,
                    "violations": [],
                    "summary": "proof accepted",
                }
            )
        ),
    )

    report = verifier.prove_contract("/tmp/project/contract.json")

    assert report.success is True
    assert report.tier1_discharge_fraction == 0.5
    assert report.tier2_discharge_fraction == 1.0
    assert report.tier3_remaining == 1
    assert report.violations == []
    assert report.summary == "proof accepted"
