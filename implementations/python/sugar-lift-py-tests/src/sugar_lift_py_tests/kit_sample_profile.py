"""An opt-in stack sampler for the kit process that survives the CLI's deadline.

Slowness is the defect (#8416). When one ``sugar.enumerate`` request runs past
the CLI's response deadline (``SUGAR_LIFT_RESPONSE_TIMEOUT_SECS``, 120 s), the
CLI kills the kit with SIGKILL: no ``atexit``, no ``finally``, no profile
written at the end. This sampler writes what it has seen while the kit runs.

Set ``SUGAR_KIT_PROFILE_DIR`` to an absolute directory and the kit starts one
daemon thread that, every ``SUGAR_KIT_PROFILE_INTERVAL_MS`` (default 20 ms),
reads the main thread's Python stack (``sys._current_frames``) and counts it,
and every ``SUGAR_KIT_PROFILE_FLUSH_S`` (default 5 s) replaces
``<dir>/kit-profile-<pid>.json`` atomically with the aggregate so far:

* ``self``: the leaf frame of each sample (where the time is spent);
* ``inclusive``: every distinct frame on the stack, once per sample (which
  function holds the time, recursion counted once);
* ``edges``: every distinct caller -> callee pair on the stack, once per
  sample (who calls the hot function, and how much of it);
* ``stacks``: folded stacks, root first, cut to the ``STACK_TAIL`` frames
  nearest the leaf;
* ``requests``: samples per RPC method (``sugar.enumerate:universe``, ...)
  and the request in flight at the last flush;
* ``lastStack``: the stack of the last sample, leaf first.

A killed kit loses at most one flush interval. Each list keeps its ``TOP``
heaviest rows, so a file is a few tens of kilobytes whatever the run's length.

The sampler is an instrument, never a step of the lift: it reads frames and
writes a file outside the project, and nothing in the kit reads it back. With
the variable unset nothing starts.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from types import CodeType, FrameType
from typing import Any, Callable, Mapping

ENV_DIR = "SUGAR_KIT_PROFILE_DIR"
ENV_INTERVAL_MS = "SUGAR_KIT_PROFILE_INTERVAL_MS"
ENV_FLUSH_S = "SUGAR_KIT_PROFILE_FLUSH_S"
DEFAULT_INTERVAL_S = 0.02
DEFAULT_FLUSH_S = 5.0
TOP = 60
STACK_TAIL = 40  # frames nearest the leaf kept in a folded stack
LAST_STACK_FRAMES = 200
SCHEMA = "sugar-kit-sample-profile/1"


def _float_env(environ: Mapping[str, str], name: str, default: float, scale: float) -> float:
    raw = environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw) * scale
    except ValueError:
        return default
    return value if value > 0 else default


class StackSampler:
    """Counts one thread's Python stacks and writes the aggregate to a file."""

    def __init__(
        self,
        out_path: Path,
        *,
        thread_id: int,
        interval_s: float = DEFAULT_INTERVAL_S,
        flush_s: float = DEFAULT_FLUSH_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.out_path = out_path
        self.thread_id = thread_id
        self.interval_s = interval_s
        self.flush_s = flush_s
        self.clock = clock
        self.started = clock()
        self.samples = 0
        self.max_depth = 0
        self.self_counts: Counter[str] = Counter()
        self.inclusive: Counter[str] = Counter()
        self.edges: Counter[str] = Counter()
        self.stacks: Counter[str] = Counter()
        self.requests: Counter[str] = Counter()
        self.request: str | None = None
        self.request_id: Any = None
        self.request_started: float | None = None
        self.last_stack: list[str] = []
        self.flushes = 0
        self._keys: dict[CodeType, str] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- keys ---------------------------------------------------------------

    def key(self, code: CodeType) -> str:
        """``<dir>/<file>:<first line>:<qualified name>``, cached per code object."""
        known = self._keys.get(code)
        if known is None:
            path = code.co_filename.replace("\\", "/")
            short = "/".join(path.rsplit("/", 2)[-2:])
            name = getattr(code, "co_qualname", code.co_name)
            known = f"{short}:{code.co_firstlineno}:{name}"
            self._keys[code] = known
        return known

    # -- sampling -----------------------------------------------------------

    def note_request(self, label: str | None, request_id: Any = None) -> None:
        """The RPC request the main thread is serving now (None between requests)."""
        self.request = label
        self.request_id = request_id
        self.request_started = self.clock() if label is not None else None

    def sample_frame(self, frame: FrameType | None) -> None:
        keys: list[str] = []
        while frame is not None:
            keys.append(self.key(frame.f_code))
            frame = frame.f_back
        if not keys:
            return
        self.samples += 1
        self.max_depth = max(self.max_depth, len(keys))
        self.self_counts[keys[0]] += 1
        self.inclusive.update(set(keys))
        self.edges.update({f"{caller} -> {callee}" for callee, caller in zip(keys, keys[1:])})
        self.stacks[";".join(reversed(keys[:STACK_TAIL]))] += 1
        self.requests[self.request or "(between requests)"] += 1
        self.last_stack = keys[:LAST_STACK_FRAMES]

    def sample_once(self) -> None:
        self.sample_frame(sys._current_frames().get(self.thread_id))

    # -- writing ------------------------------------------------------------

    @staticmethod
    def _top(counts: Counter[str], total: int) -> list[dict[str, Any]]:
        return [
            {"frame": name, "samples": n, "share": round(n / total, 4) if total else 0.0}
            for name, n in counts.most_common(TOP)
        ]

    def snapshot(self) -> dict[str, Any]:
        now = self.clock()
        total = self.samples
        return {
            "schema": SCHEMA,
            "pid": os.getpid(),
            "elapsedSeconds": round(now - self.started, 3),
            "intervalSeconds": self.interval_s,
            "samples": total,
            "maxDepth": self.max_depth,
            "distinctFrames": len(self._keys),
            "request": {
                "inFlight": self.request,
                "id": self.request_id,
                "seconds": (
                    round(now - self.request_started, 3)
                    if self.request_started is not None
                    else None
                ),
            },
            "requests": dict(self.requests.most_common()),
            "self": self._top(self.self_counts, total),
            "inclusive": self._top(self.inclusive, total),
            "edges": self._top(self.edges, total),
            "stacks": [
                {"stack": stack, "samples": n} for stack, n in self.stacks.most_common(TOP)
            ],
            "lastStack": self.last_stack,
        }

    def flush(self) -> None:
        """Replace the profile file with the aggregate so far (atomic rename)."""
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.out_path.with_name(self.out_path.name + ".tmp")
        tmp.write_text(json.dumps(self.snapshot(), sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.out_path)
        self.flushes += 1

    # -- the thread ---------------------------------------------------------

    def _run(self) -> None:
        next_flush = self.clock() + self.flush_s
        while not self._stop.wait(self.interval_s):
            try:
                self.sample_once()
                if self.clock() >= next_flush:
                    self.flush()
                    next_flush = self.clock() + self.flush_s
            except (OSError, ValueError, TypeError):
                # A full disk or an odd frame costs this flush, never the kit.
                continue

    def start(self) -> "StackSampler":
        self._thread = threading.Thread(
            target=self._run, name="sugar-kit-sample-profile", daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2 * self.interval_s + 1)
        try:
            self.flush()
        except OSError:
            pass


_ACTIVE: StackSampler | None = None


def start_from_env(environ: Mapping[str, str] | None = None) -> StackSampler | None:
    """Start the sampler on the calling thread when ``SUGAR_KIT_PROFILE_DIR`` is set."""
    global _ACTIVE
    environ = os.environ if environ is None else environ
    directory = environ.get(ENV_DIR)
    if not directory or _ACTIVE is not None:
        return _ACTIVE
    out_path = Path(directory) / f"kit-profile-{os.getpid()}.json"
    sampler = StackSampler(
        out_path,
        thread_id=threading.get_ident(),
        interval_s=_float_env(environ, ENV_INTERVAL_MS, DEFAULT_INTERVAL_S, 0.001),
        flush_s=_float_env(environ, ENV_FLUSH_S, DEFAULT_FLUSH_S, 1.0),
    )
    try:
        sampler.flush()  # the file exists from the start: a run killed early still has one
    except OSError:
        return None
    _ACTIVE = sampler.start()
    return _ACTIVE


def note_request(label: str | None, request_id: Any = None) -> None:
    """Tag the samples that follow with the RPC request being served."""
    if _ACTIVE is not None:
        _ACTIVE.note_request(label, request_id)
