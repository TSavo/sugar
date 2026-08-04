"""Teeth: suite plugin emits job-log heartbeats (not TTY-gated pytest -q bars)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
TOOLS = ROOT / "tools"


def _identity(path: Path) -> Path:
    """Minimal identity blob that SuiteReporter will accept."""
    stamp = "blake3-512_" + ("ab" * 64)
    extras = "cd" * 32
    identity = {
        "environmentIdentityHash": "ee" * 32,
        "sourceStamp": {"value": stamp},
        "dependencyAuthority": {
            "testExtraInputHash": extras,
            "declared": {"optional-dependencies": {"test": ["pytest"]}},
        },
    }
    path.write_text(json.dumps(identity) + "\n", encoding="utf-8")
    return path


def test_suite_plugin_job_log_emits_running_counts(tmp_path: Path) -> None:
    """Live pytest load of the plugin: JOB_LOG lines with pass/fail as tests finish."""
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_sample.py").write_text(
        textwrap.dedent(
            """\
            def test_one():
                assert True

            def test_two():
                assert True

            def test_three():
                assert False
            """
        ),
        encoding="utf-8",
    )
    identity = _identity(tmp_path / "identity.json")
    report = tmp_path / "suite-report.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(TOOLS), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    env["SUITE_JOB_LOG_EVERY_N"] = "1"
    env["JOB_LOG_MAX_SILENCE_S"] = "60"
    env["GITHUB_SHA"] = "deadbeef" * 5
    proc = subprocess.run(
        [
            sys.executable,
            "-u",
            "-m",
            "pytest",
            str(tests),
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "python_package_suite_report",
            f"--suite-report={report}",
            f"--suite-identity={identity}",
            "--suite-order=canonical",
            "--suite-commit=deadbeef",
            "--suite-binary-stamp=blake3-512_" + ("ab" * 64),
            "--suite-label=tooth",
            "--suite-shard-index=6",
            "--suite-shard-count=8",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert "JOB_LOG" in out, out
    assert "suite-pytest-shard-06-of-8" in out or "suite-pytest" in out, out
    assert "collection_done" in out, out
    # Running counts accumulate (not only an end summary).
    assert "passed=" in out, out
    assert "failed=" in out, out
    assert report.is_file(), (proc.returncode, out)
    body = json.loads(report.read_text(encoding="utf-8"))
    assert body["counts"]["passed"] == 2
    assert body["counts"]["failed"] == 1


def test_plugin_source_wires_heartbeat_hooks() -> None:
    """Structural tooth: the plugin owns logstart + logreport heartbeats."""
    src = (TOOLS / "python_package_suite_report.py").read_text(encoding="utf-8")
    assert "JobLogHeartbeat" in src
    assert "pytest_runtest_logstart" in src
    assert "_heartbeat_after_outcome" in src
    assert "SUITE_JOB_LOG_EVERY_N" in src
    # Never the TTY-only progress path as the sole channel.
    assert "isatty" not in src
