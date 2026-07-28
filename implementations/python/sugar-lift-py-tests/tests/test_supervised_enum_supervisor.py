"""Supervised persistent enum worker: reuse, timeout kill, crash restart."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import textwrap

import pytest

import sys
import json
import subprocess

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_SPEC = importlib.util.spec_from_file_location(
    "_supervised_enum_supervisor",
    _SCRIPTS / "_supervised_enum_supervisor.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_SUP = importlib.util.module_from_spec(_SPEC)
sys.modules["_supervised_enum_supervisor"] = _SUP
_SPEC.loader.exec_module(_SUP)


def _write(tmp: Path, name: str, source: str) -> Path:
    path = tmp / name
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def test_supervised_scan_completes_clean_and_typed_gap(tmp_path: Path) -> None:
    clean = _write(tmp_path, "clean.py", "def a(z):\n    return z\n")
    gap = _write(
        tmp_path,
        "gap.py",
        "def a():\n    with open('x'):\n        pass\n",
    )
    rows = _SUP.scan_paths([clean, gap], root=tmp_path, file_timeout=30.0)
    assert [r.file for r in rows] == ["clean.py", "gap.py"]
    assert rows[0].category == "completed"
    assert rows[1].category == "typed-gap"
    # Healthy files share a worker — zero restarts expected for this pair.
    assert rows[0].worker_restarts == 0
    assert rows[1].worker_restarts == 0


def test_supervised_timeout_restarts_and_continues(tmp_path: Path, monkeypatch) -> None:
    # Construction does not execute body sleep(); plant hangs the worker.
    sleeper = _write(tmp_path, "sleep.py", "def a():\n    return 1\n")
    after = _write(tmp_path, "after.py", "def a(z):\n    return z\n")
    monkeypatch.setenv("SUGAR_SUPERVISOR_PLANT_TIMEOUT", "sleep.py")
    supervisor = _SUP.SupervisedEnumSupervisor(
        corpus_root=tmp_path,
        file_timeout=1.0,
        allow_local_demand_derivation=True,
    )
    try:
        timed_out = supervisor.lift_file(sleeper, "sleep.py")
        supervisor.file_timeout = 30.0
        completed = supervisor.lift_file(after, "after.py")
    finally:
        supervisor.stop()
    assert timed_out.file == "sleep.py"
    assert timed_out.category == "timeout"
    assert timed_out.worker_restarts >= 1
    assert completed.file == "after.py"
    assert completed.category == "completed"


def test_supervised_bare_exception_keeps_going(tmp_path: Path, monkeypatch) -> None:
    bad = _write(tmp_path, "bad.py", "def a():\n    return 1\n")
    good = _write(tmp_path, "good.py", "def a(z):\n    return z\n")
    monkeypatch.setenv("SUGAR_SUPERVISOR_PLANT_BARE", "bad.py")
    rows = _SUP.scan_paths([bad, good], root=tmp_path, file_timeout=30.0)
    assert rows[0].category == "bare-exception"
    assert "planted bare" in rows[0].stderr_tail
    assert rows[1].category == "completed"


def test_worker_refuses_file_before_frozen_context_initialization(
    tmp_path: Path,
) -> None:
    source = _write(tmp_path, "clean.py", "def a(z):\n    return z\n")
    worker = subprocess.Popen(
        [sys.executable, str(_SCRIPTS / "_supervised_enum_worker.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert worker.stdin is not None and worker.stdout is not None
    try:
        assert json.loads(worker.stdout.readline())["kind"] == "ready"
        worker.stdin.write(
            json.dumps(
                {"kind": "lift", "path": str(source), "rel": "clean.py"}
            )
            + "\n"
        )
        worker.stdin.flush()
        refusal = json.loads(worker.stdout.readline())
        assert refusal == {
            "kind": "lift-refusal",
            "file": "clean.py",
            "coordinate": "supervised-enum-worker.construction-context",
            "reason": "authenticated frozen construction context was not initialized",
        }
    finally:
        worker.stdin.write(json.dumps({"kind": "shutdown"}) + "\n")
        worker.stdin.flush()
        worker.wait(timeout=5)
