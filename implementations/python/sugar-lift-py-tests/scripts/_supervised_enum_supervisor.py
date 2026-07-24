"""Supervised persistent enumeration worker for CI floors.

Topology:
  - One long-lived worker process reuses enum caches across healthy files.
  - Parent records the current file *before* dispatch.
  - On 30s silence/timeout: kill worker, terminal=timeout for that file, restart.
  - On signal death: terminal=native-crash for that file, restart.
  - On lift-error / bare exception: terminal=bare-exception, keep worker.
  - On completed / typed-gap: keep worker.
  - Every file gets exactly one terminal row before the scan ends.

Worker invokes the enumeration protocol only (never preconstruction).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


_WORKER = Path(__file__).resolve().parent / "_supervised_enum_worker.py"


@dataclass(frozen=True)
class FileTerminal:
    """One conserved per-file outcome from the supervised scan."""

    file: str
    category: str  # completed | typed-gap | bare-exception | timeout | native-crash
    returncode: int | None
    signal_name: str | None
    stderr_tail: str
    terminal: Mapping[str, Any] | None
    worker_restarts: int


class SupervisedEnumSupervisor:
    def __init__(
        self,
        *,
        file_timeout: float = 30.0,
        python: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        if file_timeout > 30:
            raise ValueError("per-file timeout may not exceed 30 seconds")
        self.file_timeout = float(file_timeout)
        self.python = python or sys.executable
        self.env = dict(env or os.environ)
        self.env.setdefault("PYTHONFAULTHANDLER", "1")
        self._proc: subprocess.Popen[str] | None = None
        self.worker_restarts = 0
        self._current_file: str | None = None

    @property
    def current_file(self) -> str | None:
        return self._current_file

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        self._proc = subprocess.Popen(
            [self.python, str(_WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=self.env,
        )
        ready = self._readline(timeout=30.0)
        if ready is None:
            self._kill()
            raise RuntimeError("supervised enum worker did not become ready")
        if ready.get("kind") == "bootstrap-error":
            self._kill()
            raise RuntimeError(
                f"supervised enum worker bootstrap failed: {ready.get('message')}"
            )
        if ready.get("kind") != "ready":
            self._kill()
            raise RuntimeError(f"supervised enum worker bad handshake: {ready!r}")

    def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is None and proc.stdin is not None:
                proc.stdin.write(json.dumps({"kind": "shutdown"}) + "\n")
                proc.stdin.flush()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._kill()
            else:
                self._kill()
        finally:
            self._proc = None

    def _kill(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        self._proc = None

    def restart(self) -> None:
        self._kill()
        self.worker_restarts += 1
        self.start()

    def _readline(self, *, timeout: float) -> dict[str, Any] | None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return None
        # Prefer select when available; fall back to blocking with alarm on POSIX.
        deadline = time.monotonic() + timeout
        import select

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            readable, _, _ = select.select([proc.stdout], [], [], remaining)
            if not readable:
                continue
            line = proc.stdout.readline()
            if line == "":
                # EOF — worker died
                return None
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return None

    def lift_file(self, path: Path, rel: str) -> FileTerminal:
        """Dispatch one file; may restart the worker on crash/timeout."""
        self.start()
        self._current_file = rel
        proc = self._proc
        assert proc is not None and proc.stdin is not None
        request = {"kind": "lift", "path": str(path.resolve()), "rel": rel}
        try:
            proc.stdin.write(json.dumps(request) + "\n")
            proc.stdin.flush()
        except BrokenPipeError:
            return self._after_death(rel, note="broken pipe on dispatch")

        response = self._readline(timeout=self.file_timeout)
        if response is None:
            # Timeout or EOF.
            rc = proc.poll()
            if rc is None:
                # Still running but silent → timeout.
                self._kill()
                self.worker_restarts += 1
                self.start()
                return FileTerminal(
                    file=rel,
                    category="timeout",
                    returncode=None,
                    signal_name=None,
                    stderr_tail=f"exceeded {self.file_timeout}s",
                    terminal=None,
                    worker_restarts=self.worker_restarts,
                )
            return self._after_death(rel, note="worker exited during lift")

        kind = response.get("kind")
        if kind == "lift-result":
            terminal = response.get("terminal")
            if not isinstance(terminal, Mapping):
                return FileTerminal(
                    file=rel,
                    category="bare-exception",
                    returncode=1,
                    signal_name=None,
                    stderr_tail="worker returned lift-result without terminal",
                    terminal=None,
                    worker_restarts=self.worker_restarts,
                )
            outcome = str(terminal.get("outcome") or "")
            if outcome in {"completed", "typed-gap"}:
                category = outcome
            else:
                category = "bare-exception"
            return FileTerminal(
                file=rel,
                category=category,
                returncode=0,
                signal_name=None,
                stderr_tail="",
                terminal=dict(terminal),
                worker_restarts=self.worker_restarts,
            )
        if kind == "lift-error":
            return FileTerminal(
                file=rel,
                category="bare-exception",
                returncode=1,
                signal_name=None,
                stderr_tail=(
                    f"{response.get('error_type')}: {response.get('message')}"
                )[-2000:],
                terminal=None,
                worker_restarts=self.worker_restarts,
            )
        return FileTerminal(
            file=rel,
            category="bare-exception",
            returncode=1,
            signal_name=None,
            stderr_tail=f"unexpected worker response: {response!r}"[-2000:],
            terminal=None,
            worker_restarts=self.worker_restarts,
        )

    def _after_death(self, rel: str, *, note: str) -> FileTerminal:
        proc = self._proc
        rc = proc.poll() if proc is not None else -1
        stderr = ""
        if proc is not None and proc.stderr is not None:
            try:
                stderr = proc.stderr.read()[-2000:]
            except Exception:  # noqa: BLE001
                stderr = ""
        signal_name = None
        category = "bare-exception"
        if rc is not None and rc < 0:
            category = "native-crash"
            try:
                signal_name = signal.Signals(-rc).name
            except ValueError:
                signal_name = f"signal-{-rc}"
        elif rc is None:
            category = "native-crash"
            rc = -1
        self._kill()
        self.worker_restarts += 1
        try:
            self.start()
        except RuntimeError as error:
            # Leave supervisor without a worker; next lift_file will retry.
            stderr = (stderr + f"\nrestart failed: {error}")[-2000:]
        return FileTerminal(
            file=rel,
            category=category,
            returncode=rc,
            signal_name=signal_name,
            stderr_tail=(stderr or note)[-2000:],
            terminal=None,
            worker_restarts=self.worker_restarts,
        )

    def scan(
        self, paths: Sequence[tuple[Path, str]]
    ) -> list[FileTerminal]:
        """Lift every (path, rel); guarantee one terminal row per file."""
        rows: list[FileTerminal] = []
        try:
            self.start()
            for path, rel in paths:
                rows.append(self.lift_file(path, rel))
        finally:
            self.stop()
        return rows


def scan_paths(
    paths: Sequence[Path],
    *,
    root: Path,
    file_timeout: float = 30.0,
) -> list[FileTerminal]:
    from _enum_floor_runtime import relative_to_root

    pairs = [(path, relative_to_root(path, root)) for path in paths]
    supervisor = SupervisedEnumSupervisor(file_timeout=file_timeout)
    return supervisor.scan(pairs)
