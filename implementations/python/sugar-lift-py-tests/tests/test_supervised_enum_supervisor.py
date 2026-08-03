"""Supervised persistent enum worker: reuse, timeout kill, crash restart."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import textwrap

import pytest

import sys
import json
import os
import subprocess

os.environ.setdefault("SUGAR_PROCESS_FLOOR_CACHE_DIR", "off")

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
# scan() imports process_floor_measurement_cache as a scripts sibling — same
# door floors open when invoked as scripts/*.py (sys.path has scripts/).
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
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
            json.dumps({"kind": "lift", "path": str(source), "rel": "clean.py"}) + "\n"
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


def test_context_init_timeout_for_population_scales() -> None:
    """Corpus and unit-test populations are different obligations."""
    assert _SUP.context_init_timeout_for_population(0) <= 60.0
    assert _SUP.context_init_timeout_for_population(1) <= 60.0
    assert _SUP.context_init_timeout_for_population(2) <= 60.0
    assert _SUP.context_init_timeout_for_population(2) < 120.0
    # Authenticated pandas order-of-magnitude → corpus budget.
    assert _SUP.context_init_timeout_for_population(1421) == 1800.0
    assert _SUP.context_init_timeout_for_population(500) == 1800.0
    assert _SUP.context_init_timeout_for_population(499) < 1800.0


def test_context_init_timeout_names_phase_not_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Init timeout must name phase + corpus_root — never 'refused: None'.

    Floors 30728650857 banked refused: None because the 30s per-file budget
    gated multi-minute provisional demand derivation over authenticated pandas.
    """
    _write(tmp_path, "clean.py", "def a(z):\n    return z\n")
    monkeypatch.setenv("SUGAR_SUPERVISOR_PLANT_INIT_HANG", "1")
    supervisor = _SUP.SupervisedEnumSupervisor(
        corpus_root=tmp_path,
        file_timeout=30.0,
        context_init_timeout=1.0,
        allow_local_demand_derivation=True,
    )
    try:
        with pytest.raises(RuntimeError) as raised:
            supervisor.start()
        message = str(raised.value)
        assert "refused: None" not in message
        assert "mode=timeout" in message
        assert "last_phase='planted-init-hang'" in message
        assert f"corpus_root={tmp_path.resolve()}" in message
        assert "coordinate=supervised-enum-worker.construction-context" in message
        assert "context_init_timeout_s=1.0" in message
    finally:
        supervisor.stop()


def test_tiny_population_init_hang_fails_in_seconds_not_corpus_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Suite hang class: tiny tree must not inherit 1800s corpus init budget.

    Shard 3 job 91456853960: worker sat 23+ minutes under the corpus default.
    Population-scaled default makes unit-spawned workers fail in seconds.
    """
    import time

    _write(tmp_path, "clean.py", "def a(z):\n    return z\n")
    monkeypatch.setenv("SUGAR_SUPERVISOR_PLANT_INIT_HANG", "1")
    # No explicit context_init_timeout — must derive short budget from population.
    supervisor = _SUP.SupervisedEnumSupervisor(
        corpus_root=tmp_path,
        file_timeout=30.0,
        allow_local_demand_derivation=True,
    )
    assert supervisor.population_file_count == 1
    assert supervisor.context_init_timeout <= 60.0
    assert supervisor.context_init_timeout < 1800.0
    try:
        t0 = time.perf_counter()
        with pytest.raises(RuntimeError) as raised:
            supervisor.start()
        elapsed = time.perf_counter() - t0
        message = str(raised.value)
        assert elapsed < 30.0, (
            f"tiny-population init hang took {elapsed:.1f}s; "
            "must fail in seconds, not the 1800s corpus budget"
        )
        assert "refused: None" not in message
        assert "mode=timeout" in message
        assert "population_file_count=1" in message
        assert "last_phase='planted-init-hang'" in message
        assert "context_init_timeout_s=1800" not in message
        assert f"context_init_timeout_s={supervisor.context_init_timeout}" in message
    finally:
        supervisor.stop()


def test_context_init_missing_corpus_root_names_artifact(tmp_path: Path) -> None:
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
                {
                    "kind": "initialize",
                    "corpus_root": "",
                    "allow_local_demand_derivation": True,
                }
            )
            + "\n"
        )
        worker.stdin.flush()
        response = None
        for _ in range(10):
            line = worker.stdout.readline()
            assert line, "worker exited without initialize-refusal"
            response = json.loads(line)
            if response.get("kind") != "initialize-progress":
                break
        assert response is not None
        assert response["kind"] == "initialize-refusal"
        assert response["phase"] == "resolve-corpus-root"
        assert "corpus_root is empty" in response["reason"]
    finally:
        worker.stdin.write(json.dumps({"kind": "shutdown"}) + "\n")
        worker.stdin.flush()
        worker.wait(timeout=5)


def test_context_init_nonexistent_root_names_path(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-corpus"
    supervisor = _SUP.SupervisedEnumSupervisor(
        corpus_root=missing,
        file_timeout=30.0,
        context_init_timeout=30.0,
        allow_local_demand_derivation=True,
    )
    try:
        with pytest.raises(RuntimeError) as raised:
            supervisor.start()
        message = str(raised.value)
        assert "refused: None" not in message
        assert "does not exist" in message or "resolve-corpus-root" in message
        assert str(missing.resolve()) in message
    finally:
        supervisor.stop()


def test_named_lift_error_tail_never_none_none() -> None:
    """Sibling: incomplete lift-error must not serialize as 'None: None'."""
    assert "None: None" not in _SUP._named_lift_error_tail({})
    assert "no error_type" in _SUP._named_lift_error_tail({})
    assert "missing error_type" in _SUP._named_lift_error_tail({"message": "x"})
    assert "(message field absent)" in _SUP._named_lift_error_tail(
        {"error_type": "RuntimeError"}
    )
    assert (
        _SUP._named_lift_error_tail({"error_type": "RuntimeError", "message": "boom"})
        == "RuntimeError: boom"
    )


def test_lift_error_incomplete_payload_names_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sibling: incomplete lift-error body reaches FileTerminal named."""
    source = _write(tmp_path, "clean.py", "def a(z):\n    return z\n")
    supervisor = _SUP.SupervisedEnumSupervisor(
        corpus_root=tmp_path,
        allow_local_demand_derivation=True,
    )
    try:
        supervisor.start()
        # Inject incomplete lift-error as if worker returned it.
        original = supervisor._readline

        def fake_readline(*, timeout: float):
            return {"kind": "lift-error"}  # no error_type, no message

        supervisor._readline = fake_readline  # type: ignore[method-assign]
        row = supervisor.lift_file(source, "clean.py")
        supervisor._readline = original  # type: ignore[method-assign]
        assert row.category == "bare-exception"
        assert "None: None" not in row.stderr_tail
        assert "no error_type" in row.stderr_tail or "lift-error" in row.stderr_tail
    finally:
        supervisor.stop()
