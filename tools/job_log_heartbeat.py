#!/usr/bin/env python3
"""Job-log narration: never let a >30s path look dead in Actions.

DOCTRINE (binding): if work can run longer than 30 seconds, it must emit a
named phase or a count within 30 seconds, and every 30 seconds after — TO THE
JOB LOG (process stdout/stderr that CI captures). File-only progress (TTY-gated
tqdm, out-dir/progress.log) is identical to no instrumentation.

Four corollaries:
  1. To the job log, not a file.
  2. Never fuse phases into one CI step (caller's workflow concern).
  3. Running counts as they accumulate.
  4. A crash is not a measurement (caller's enrollment concern).

This module is the shared narrator for long Python measurement paths.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# Max silence on the job log. Override only for tests.
JOB_LOG_MAX_SILENCE_S = float(os.environ.get("JOB_LOG_MAX_SILENCE_S", "30"))


def narrate(msg: str) -> None:
    """Print one line to the job log with flush. Never raise for flush failures."""
    print(msg, flush=True)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 — never fail the measurement for a flush
        pass


class JobLogHeartbeat:
    """Rate-limited phase/count lines for the Actions job log.

    Call ``tick`` on every meaningful progress event. Call ``force`` for phase
    boundaries. A background ``watch`` keeps emitting if the main thread stalls
    inside one long unit of work.
    """

    def __init__(
        self,
        phase: str,
        *,
        total: int | None = None,
        max_silence_s: float | None = None,
    ) -> None:
        self.phase = phase
        self.total = total
        self.n = 0
        self.extra: dict[str, Any] = {}
        self.max_silence_s = (
            JOB_LOG_MAX_SILENCE_S if max_silence_s is None else float(max_silence_s)
        )
        self._t0 = time.monotonic()
        self._last_emit = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self.tick(force=True, status="start")

    def _line(self, *, status: str = "") -> str:
        elapsed = time.monotonic() - self._t0
        if self.total is not None:
            count = f"n={self.n}/{self.total}"
        else:
            count = f"n={self.n}"
        bits = [f"phase={self.phase}", count, f"elapsed_s={elapsed:.1f}"]
        if status:
            bits.append(f"status={status}")
        for key, value in sorted(self.extra.items()):
            bits.append(f"{key}={value}")
        return "JOB_LOG " + " ".join(bits)

    def tick(
        self,
        *,
        n: int | None = None,
        status: str = "",
        force: bool = False,
        **extra: Any,
    ) -> None:
        with self._lock:
            if n is not None:
                self.n = int(n)
            if extra:
                self.extra.update(extra)
            now = time.monotonic()
            if not force and (now - self._last_emit) < self.max_silence_s:
                return
            self._last_emit = now
            line = self._line(status=status)

        narrate(line)

    def watch(self) -> None:
        """Daemon thread: re-emit at max silence if the main thread stalls."""
        if self._watch_thread is not None:
            return

        def _loop() -> None:
            while not self._stop.wait(self.max_silence_s):
                self.tick(force=True, status="alive")

        self._watch_thread = threading.Thread(
            target=_loop,
            name=f"job-log-heartbeat-{self.phase}",
            daemon=True,
        )
        self._watch_thread.start()

    def stop(self, *, status: str = "end") -> None:
        self._stop.set()
        self.tick(force=True, status=status)


def run_phase(
    phase: str,
    fn: Callable[[], T],
    *,
    total: int | None = None,
    max_silence_s: float | None = None,
) -> T:
    """Run ``fn`` under a named phase with ≤30s job-log silence."""
    beat = JobLogHeartbeat(phase, total=total, max_silence_s=max_silence_s)
    beat.watch()
    try:
        result = fn()
        beat.stop(status="ok")
        return result
    except BaseException:
        beat.stop(status="failed")
        raise
