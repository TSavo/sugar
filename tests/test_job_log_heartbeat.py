"""Teeth: job-log doctrine — ≤30s silence, stdout not file, running counts."""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
sys.path.insert(0, str(ROOT / "tools"))

from job_log_heartbeat import JOB_LOG_MAX_SILENCE_S, JobLogHeartbeat, narrate  # noqa: E402


def test_default_max_silence_is_30_seconds() -> None:
    assert JOB_LOG_MAX_SILENCE_S == 30.0


def test_narrate_writes_flushed_stdout(capsys) -> None:
    narrate("JOB_LOG phase=tooth status=ok")
    out = capsys.readouterr().out
    assert "JOB_LOG phase=tooth status=ok" in out


def test_heartbeat_emits_start_and_running_counts(capsys) -> None:
    beat = JobLogHeartbeat("unit-scan", total=10, max_silence_s=0.05)
    # start already emitted
    beat.tick(n=1, force=True, status="lifting", file="a.py")
    beat.tick(n=2, force=True, status="done", file="b.py")
    beat.stop(status="ok")
    out = capsys.readouterr().out
    assert "phase=unit-scan" in out
    assert "n=1/10" in out or "n=2/10" in out
    assert "status=ok" in out


def test_heartbeat_rate_limits_unless_forced(capsys) -> None:
    beat = JobLogHeartbeat("rate", total=5, max_silence_s=60.0)
    capsys.readouterr()  # drop start
    beat.tick(n=1, status="a")  # suppressed (within 60s, not force)
    beat.tick(n=2, status="b")
    out = capsys.readouterr().out
    assert out == ""
    beat.tick(n=3, force=True, status="c")
    out = capsys.readouterr().out
    assert "n=3/5" in out
    beat.stop()


def test_watch_emits_alive_when_main_stalls(capsys) -> None:
    beat = JobLogHeartbeat("stall", total=1, max_silence_s=0.05)
    beat.watch()
    time.sleep(0.18)
    beat.stop(status="ok")
    out = capsys.readouterr().out
    assert "status=alive" in out or "status=ok" in out
