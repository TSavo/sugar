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
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

_WORKER = Path(__file__).resolve().parent / "_supervised_enum_worker.py"

# Context init walks the full corpus for provisional demand rows when no
# shared demand table is supplied. Authenticated pandas (~1421 files) is
# multi-minute work — never share the 30s per-file lift timeout.
# Floors run 30728650857: POPULATION → refused: None at ~30.0s exactly.
_DEFAULT_CONTEXT_INIT_TIMEOUT = 1800.0


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


def _named_lift_error_tail(response: Mapping[str, Any]) -> str:
    """Serialize lift-error without 'None: None' (criterion-3 nameless refusal)."""
    error_type = response.get("error_type")
    message = response.get("message")
    if error_type is None and message is None:
        return (
            "lift-error with no error_type and no message; "
            f"worker response keys={sorted(response)!r}; "
            "coordinate=supervised-enum-supervisor.lift-error"
        )
    if error_type is None:
        return (
            "lift-error missing error_type; "
            f"message={message!r}; "
            "coordinate=supervised-enum-supervisor.lift-error"
        )
    if message is None:
        return (
            f"{error_type}: (message field absent); "
            "coordinate=supervised-enum-supervisor.lift-error"
        )
    return f"{error_type}: {message}"


class SupervisedEnumSupervisor:
    def __init__(
        self,
        *,
        file_timeout: float = 30.0,
        context_init_timeout: float = _DEFAULT_CONTEXT_INIT_TIMEOUT,
        python: str | None = None,
        env: Mapping[str, str] | None = None,
        corpus_root: Path,
        demand_table_path: Path | None = None,
        allow_local_demand_derivation: bool = False,
    ) -> None:
        if file_timeout > 30:
            raise ValueError("per-file timeout may not exceed 30 seconds")
        if context_init_timeout <= 0:
            raise ValueError("context_init_timeout must be positive")
        self.file_timeout = float(file_timeout)
        self.context_init_timeout = float(context_init_timeout)
        self.python = python or sys.executable
        self.env = dict(env or os.environ)
        self.env.setdefault("PYTHONFAULTHANDLER", "1")
        self.corpus_root = corpus_root.resolve()
        self.demand_table_path = (
            None if demand_table_path is None else demand_table_path.resolve()
        )
        self.allow_local_demand_derivation = allow_local_demand_derivation
        self._proc: subprocess.Popen[str] | None = None
        self.worker_restarts = 0
        self._current_file: str | None = None
        self._stderr_chunks: list[str] = []
        self._stderr_thread: threading.Thread | None = None

    @property
    def current_file(self) -> str | None:
        return self._current_file

    def _start_stderr_drain(self) -> None:
        """Drain worker stderr so a full pipe cannot deadlock the lift."""
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        self._stderr_chunks = []

        def _drain() -> None:
            try:
                assert proc.stderr is not None
                for line in proc.stderr:
                    self._stderr_chunks.append(line)
            except Exception:  # noqa: BLE001
                return

        self._stderr_thread = threading.Thread(
            target=_drain, name="supervised-enum-stderr", daemon=True
        )
        self._stderr_thread.start()

    def _worker_stderr_tail(self, *, limit: int = 2000) -> str:
        text = "".join(self._stderr_chunks)
        return text[-limit:] if text else ""

    def _named_context_init_failure(
        self,
        *,
        response: Mapping[str, Any] | None,
        last_progress: Mapping[str, Any] | None,
        elapsed: float,
        timed_out: bool,
    ) -> RuntimeError:
        """Refusal that names the artifact — never 'refused: None'."""
        proc = self._proc
        rc = proc.poll() if proc is not None else None
        stderr_tail = self._worker_stderr_tail()
        demand = (
            str(self.demand_table_path) if self.demand_table_path is not None else None
        )
        parts = [
            "supervised enum worker context initialization refused",
            "coordinate=supervised-enum-worker.construction-context",
            f"corpus_root={self.corpus_root}",
            f"demand_table_path={demand!r}",
            f"allow_local_demand_derivation={self.allow_local_demand_derivation}",
            f"context_init_timeout_s={self.context_init_timeout}",
            f"elapsed_s={elapsed:.1f}",
        ]
        if timed_out:
            parts.append("mode=timeout")
            parts.append(
                "fix=pass demand_table_path (shared python-demand-table) or "
                "raise context_init_timeout; local provisional demand derivation "
                "over authenticated pandas is multi-minute work and must not "
                "share the 30s per-file lift timeout"
            )
        elif rc is not None:
            parts.append("mode=worker-exited")
            parts.append(f"worker_returncode={rc}")
        else:
            parts.append("mode=no-response")
        if last_progress is not None:
            parts.append(f"last_phase={last_progress.get('phase')!r}")
            parts.append(f"last_progress={dict(last_progress)!r}")
        else:
            parts.append("last_phase=None")
            parts.append(
                "artifact_unseen=no initialize-progress/context-ready line from worker"
            )
        if response is not None:
            kind = response.get("kind")
            parts.append(f"response_kind={kind!r}")
            if kind == "initialize-refusal":
                reason = response.get("reason")
                if reason is None or reason == "":
                    parts.append(
                        "reason=(absent); "
                        "initialize-refusal payload carried no reason string"
                    )
                else:
                    parts.append(f"reason={reason!r}")
                parts.append(f"phase={response.get('phase')!r}")
            else:
                parts.append(f"response={dict(response)!r}")
        if stderr_tail:
            parts.append(f"worker_stderr_tail={stderr_tail!r}")
        return RuntimeError("; ".join(parts))

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
        self._start_stderr_drain()
        ready = self._readline(timeout=30.0)
        if ready is None:
            stderr_tail = self._worker_stderr_tail()
            rc = self._proc.poll() if self._proc is not None else None
            self._kill()
            raise RuntimeError(
                "supervised enum worker did not become ready; "
                f"worker_returncode={rc}; worker_stderr_tail={stderr_tail!r}; "
                f"worker={_WORKER}; "
                "artifact=no ready/bootstrap-error line before handshake timeout"
            )
        if ready.get("kind") == "bootstrap-error":
            message = ready.get("message")
            self._kill()
            if message is None or message == "":
                raise RuntimeError(
                    "supervised enum worker bootstrap failed: "
                    "message field absent from bootstrap-error payload; "
                    f"response_keys={sorted(ready)!r}; worker={_WORKER}; "
                    "coordinate=supervised-enum-worker.bootstrap"
                )
            raise RuntimeError(
                "supervised enum worker bootstrap failed: "
                f"message={message!r}; worker={_WORKER}; "
                "coordinate=supervised-enum-worker.bootstrap"
            )
        if ready.get("kind") != "ready":
            self._kill()
            raise RuntimeError(
                "supervised enum worker bad handshake: "
                f"response={ready!r}; worker={_WORKER}"
            )
        assert self._proc.stdin is not None
        initialize = {"kind": "initialize", "corpus_root": str(self.corpus_root)}
        if self.demand_table_path is not None:
            initialize["demand_table_path"] = str(self.demand_table_path)
        initialize["allow_local_demand_derivation"] = self.allow_local_demand_derivation
        self._proc.stdin.write(json.dumps(initialize) + "\n")
        self._proc.stdin.flush()

        # Drain progress heartbeats until context-ready, a named refusal, or
        # the context-init budget (NOT the 30s per-file lift budget).
        deadline = time.monotonic() + self.context_init_timeout
        last_progress: Mapping[str, Any] | None = None
        started = time.monotonic()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                error = self._named_context_init_failure(
                    response=None,
                    last_progress=last_progress,
                    elapsed=time.monotonic() - started,
                    timed_out=True,
                )
                self._kill()
                raise error
            message = self._readline(timeout=remaining)
            if message is None:
                timed_out = time.monotonic() >= deadline
                if (
                    not timed_out
                    and self._proc is not None
                    and self._proc.poll() is None
                ):
                    continue
                error = self._named_context_init_failure(
                    response=None,
                    last_progress=last_progress,
                    elapsed=time.monotonic() - started,
                    timed_out=timed_out
                    or (self._proc is not None and self._proc.poll() is None),
                )
                self._kill()
                raise error
            kind = message.get("kind")
            if kind == "initialize-progress":
                last_progress = message
                continue
            if kind == "context-ready":
                return
            error = self._named_context_init_failure(
                response=message,
                last_progress=last_progress,
                elapsed=time.monotonic() - started,
                timed_out=False,
            )
            self._kill()
            raise error

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
                stderr_tail=_named_lift_error_tail(response)[-2000:],
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

    def scan(self, paths: Sequence[tuple[Path, str]]) -> list[FileTerminal]:
        """Lift every (path, rel); guarantee one terminal row per file.

        Content-addressed hits (tip × corpus × axis × file-content cid × …)
        skip the worker lift. Misses are full honest measurement. Only
        completed / typed-gap / bare-exception rows are banked.
        """
        # Sibling module lives next to this file under scripts/.
        _scripts = str(Path(__file__).resolve().parent)
        if _scripts not in sys.path:
            sys.path.insert(0, _scripts)
        from process_floor_measurement_cache import (
            DEFAULT_AXIS,
            MeasurementKey,
            ProcessFloorTerminalCache,
            CacheRefuse,
            corpus_manifest_cid_for_paths,
            demand_table_cid,
            file_content_cid,
            payload_to_file_terminal,
            resolve_cache_root,
            resolve_measurement_tip,
            terminal_to_payload,
        )

        cache_root = resolve_cache_root()
        cache = ProcessFloorTerminalCache(cache_root) if cache_root is not None else None
        tip = resolve_measurement_tip()
        demand_cid = demand_table_cid(self.demand_table_path)
        timeout_ms = int(round(self.file_timeout * 1000))
        path_list = [path for path, _rel in paths]
        corpus_cid = corpus_manifest_cid_for_paths(self.corpus_root, path_list)

        ordered: list[FileTerminal | None] = [None] * len(paths)
        pending: list[tuple[int, Path, str, MeasurementKey]] = []
        hits = 0
        refuses = 0

        if cache is not None:
            for index, (path, rel) in enumerate(paths):
                key = MeasurementKey(
                    tip=tip,
                    corpus_manifest_cid=corpus_cid,
                    axis=DEFAULT_AXIS,
                    file_content_cid=file_content_cid(path),
                    demand_table_cid=demand_cid,
                    file_timeout_ms=timeout_ms,
                )
                try:
                    payload = cache.lookup(key)
                except CacheRefuse:
                    refuses += 1
                    pending.append((index, path, rel, key))
                    continue
                if payload is None:
                    pending.append((index, path, rel, key))
                    continue
                ordered[index] = payload_to_file_terminal(payload, worker_restarts=0)
                hits += 1
        else:
            for index, (path, rel) in enumerate(paths):
                key = MeasurementKey(
                    tip=tip,
                    corpus_manifest_cid=corpus_cid,
                    axis=DEFAULT_AXIS,
                    file_content_cid=file_content_cid(path),
                    demand_table_cid=demand_cid,
                    file_timeout_ms=timeout_ms,
                )
                pending.append((index, path, rel, key))

        if pending:
            try:
                self.start()
                for index, path, rel, key in pending:
                    measured = self.lift_file(path, rel)
                    ordered[index] = measured
                    if cache is not None:
                        payload = terminal_to_payload(
                            file=measured.file,
                            category=measured.category,
                            returncode=measured.returncode,
                            signal_name=measured.signal_name,
                            stderr_tail=measured.stderr_tail,
                            terminal=measured.terminal,
                        )
                        cache.store(key, payload)
            finally:
                self.stop()

        if cache is not None:
            print(
                "PROCESS-FLOOR-CACHE: "
                f"root={cache.root} tip={tip} "
                f"hits={hits} misses={len(pending)} refuses={refuses} "
                f"corpusManifestCid={corpus_cid[:48]}…"
            )

        rows: list[FileTerminal] = []
        for index, row in enumerate(ordered):
            if row is None:
                raise RuntimeError(
                    f"process floor scan left file unmeasured at index {index}"
                )
            rows.append(row)
        return rows


def _relative_to_root(path: Path, root: Path) -> str:
    """Repo-relative locus without importing _enum_floor_runtime (scripts path)."""
    return path.resolve().relative_to(root.resolve()).as_posix()


def scan_paths(
    paths: Sequence[Path],
    *,
    root: Path,
    file_timeout: float = 30.0,
    context_init_timeout: float = _DEFAULT_CONTEXT_INIT_TIMEOUT,
    demand_table_path: Path | None = None,
) -> list[FileTerminal]:
    pairs = [(_p, _relative_to_root(_p, root)) for _p in paths]
    supervisor = SupervisedEnumSupervisor(
        file_timeout=file_timeout,
        context_init_timeout=context_init_timeout,
        corpus_root=root,
        demand_table_path=demand_table_path,
        allow_local_demand_derivation=demand_table_path is None,
    )
    return supervisor.scan(pairs)
