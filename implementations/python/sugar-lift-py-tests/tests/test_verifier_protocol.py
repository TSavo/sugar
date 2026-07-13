# SPDX-License-Identifier: MIT OR Apache-2.0
from __future__ import annotations

import json
import subprocess

import pytest

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

    def fake_run(cmd, *, capture_output, text, check, env=None, cwd=None, **_kwargs):
        assert cmd[0] == "/fake/sugar"
        assert capture_output is True
        assert text is True
        assert check is False
        # Hermetic door: every verify/prove must pin SUGAR_HOME.
        assert env is not None and env.get(
            "SUGAR_HOME"
        ), "verifier must invoke sugar with hermetic SUGAR_HOME"
        assert cwd is not None
        return completed

    monkeypatch.setattr(verifier.subprocess, "run", fake_run)


def _protocol_error_type():
    return getattr(verifier, "VerifierProtocolError", RuntimeError)


def _assert_protocol_error(error: BaseException, *, stdout: str, stderr: str) -> None:
    assert isinstance(error, verifier.VerifierProtocolError)
    assert error.stdout == stdout
    assert error.stderr == stderr
    detail = str(error).lower()
    assert "malformed" in detail
    assert "json" in detail
    assert "protocol drift" in detail


def test_verify_project_raises_on_malformed_zero_exit_cli_json(monkeypatch) -> None:
    _stub_sugar_cli(monkeypatch, _completed("not json", stderr="debug stderr"))

    with pytest.raises(_protocol_error_type()) as raised:
        verifier.verify_project("/tmp/project")

    _assert_protocol_error(raised.value, stdout="not json", stderr="debug stderr")


def test_prove_contract_raises_on_malformed_zero_exit_cli_json(monkeypatch) -> None:
    _stub_sugar_cli(monkeypatch, _completed("not json", stderr="debug stderr"))

    with pytest.raises(_protocol_error_type()) as raised:
        verifier.prove_contract("/tmp/project/contract.json")

    _assert_protocol_error(raised.value, stdout="not json", stderr="debug stderr")


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


def test_verify_project_preserves_nonzero_exit_failure_report(monkeypatch) -> None:
    _stub_sugar_cli(
        monkeypatch,
        _completed(
            "not json but ignored", stderr="verification failed hard", returncode=2
        ),
    )

    report = verifier.verify_project("/tmp/project")

    assert report.success is False
    assert report.violations == ["verification failed hard"]
    assert report.summary == "verification failed hard"


def test_prove_contract_preserves_nonzero_exit_failure_report(monkeypatch) -> None:
    _stub_sugar_cli(
        monkeypatch,
        _completed("not json but ignored", stderr="proof failed hard", returncode=2),
    )

    report = verifier.prove_contract("/tmp/project/contract.json")

    assert report.success is False
    assert report.violations == ["proof failed hard"]
    assert report.summary == "proof failed hard"
