from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import logging
import os
import threading
import time
from typing import Iterator

LOGGER = logging.getLogger("sugar_lift_py_tests.engine")
_HEARTBEAT_SECONDS = float(os.environ.get("SUGAR_ENGINE_HEARTBEAT_SECONDS", "5"))
_CYCLE_THRESHOLD = int(os.environ.get("SUGAR_ENGINE_CYCLE_THRESHOLD", "8"))
_LOCK = threading.RLock()
_ACTIVE: dict[int, list[_Frame]] = {}
_SEQUENCE = 0
_WATCHDOG_STARTED = False
_LIVE_HANDLER: logging.Handler | None = None


@dataclass(frozen=True)
class _Frame:
    sequence: int
    fingerprint: str
    sugar: str
    role: str
    site: str
    started: float


@contextmanager
def reduction_span(*, sugar: str, role: str, site: str) -> Iterator[None]:
    """Instrument the universal Sugar reduction boundary."""
    frame = _enter(sugar=sugar, role=role, site=site)
    try:
        yield
    except BaseException as error:
        _finish(
            frame,
            event="error",
            level=logging.ERROR,
            error_type=type(error).__name__,
            error=str(error),
        )
        raise
    else:
        _finish(frame, event="exit", level=logging.DEBUG)


def _enter(*, sugar: str, role: str, site: str) -> _Frame:
    global _SEQUENCE
    now = time.monotonic()
    thread_id = threading.get_ident()
    fingerprint = f"{sugar}|{role}|{site}"
    with _LOCK:
        _SEQUENCE += 1
        frame = _Frame(_SEQUENCE, fingerprint, sugar, role, site, now)
        stack = _ACTIVE.setdefault(thread_id, [])
        stack.append(frame)
        _emit(logging.DEBUG, "enter", frame, depth=len(stack), thread_id=thread_id)
        repetitions = sum(item.fingerprint == fingerprint for item in stack)
        if repetitions >= _CYCLE_THRESHOLD:
            _emit(
                logging.WARNING,
                "cycle_suspected",
                frame,
                thread_id=thread_id,
                active_repetitions=repetitions,
                active_stack=[item.fingerprint for item in stack],
            )
        _start_watchdog()
        return frame


def _finish(frame: _Frame, *, event: str, level: int, **fields) -> None:
    now = time.monotonic()
    thread_id = threading.get_ident()
    with _LOCK:
        stack = _ACTIVE.get(thread_id, [])
        if frame in stack:
            stack.remove(frame)
        if not stack:
            _ACTIVE.pop(thread_id, None)
        _emit(
            level,
            event,
            frame,
            thread_id=thread_id,
            active_depth=len(stack),
            elapsed_ms=round((now - frame.started) * 1000, 3),
            **fields,
        )


def _start_watchdog() -> None:
    global _WATCHDOG_STARTED
    if _WATCHDOG_STARTED or _HEARTBEAT_SECONDS <= 0:
        return
    _WATCHDOG_STARTED = True
    threading.Thread(
        target=_watchdog,
        name="sugar-engine-watchdog",
        daemon=True,
    ).start()


def _watchdog() -> None:
    interval = max(min(_HEARTBEAT_SECONDS, 1.0), 0.05)
    while True:
        time.sleep(interval)
        _emit_heartbeats()


def _emit_heartbeats(
    *, now: float | None = None, minimum_seconds: float | None = None
) -> None:
    now = time.monotonic() if now is None else now
    minimum = _HEARTBEAT_SECONDS if minimum_seconds is None else minimum_seconds
    with _LOCK:
        for thread_id, stack in tuple(_ACTIVE.items()):
            if not stack:
                continue
            oldest = stack[0]
            elapsed = now - oldest.started
            if elapsed < minimum:
                continue
            _emit(
                logging.WARNING,
                "heartbeat",
                oldest,
                thread_id=thread_id,
                oldest_elapsed_ms=round(elapsed * 1000, 3),
                active_depth=len(stack),
                active_stack=[item.fingerprint for item in stack],
            )


def _emit(level: int, event: str, frame: _Frame, **fields) -> None:
    if not LOGGER.isEnabledFor(level):
        return
    payload = {
        "schema": "sugar.engine.log.v1",
        "event": event,
        "sequence": frame.sequence,
        "sugar": frame.sugar,
        "role": frame.role,
        "site": frame.site,
        "fingerprint": frame.fingerprint,
        **fields,
    }
    try:
        message = json.dumps(payload, sort_keys=True, default=str)
    except RecursionError:
        # Reduction can lawfully approach Python's recursion limit. Telemetry is
        # observational and must never turn that reduction into a factory gap.
        return
    LOGGER.log(level, message)


def configure_live_log(path: str | None = None) -> None:
    """Attach an immediate JSONL file sink outside pytest's log capture."""
    global _LIVE_HANDLER
    selected = path or os.environ.get("SUGAR_ENGINE_LOG")
    if not selected or _LIVE_HANDLER is not None:
        return
    handler = logging.FileHandler(selected, mode="a", encoding="utf-8", delay=False)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.DEBUG)
    _LIVE_HANDLER = handler


configure_live_log()
