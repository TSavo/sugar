"""`ast.parse` on a dedicated big-stack worker thread.

Why this exists: CPython's compiler (invoked by `ast.parse`) guards its own
recursion with a limit tuned for the MAIN thread's default C stack. The lift
machinery reaches `ast.parse` from deeply recursive Python frames, so by the
time the C parser starts, most of the C stack is already spent -- and the
compiler's guard does not know that. The result is a hard SIGSEGV whose
position wanders with cache state and corpus order (observed as the wall
plugin dying nondeterministically with `read_line.disconnected`).

The fix: run every hot-path parse on ONE long-lived worker thread created
with a 64 MiB stack via `threading.stack_size`. The worker's stack is always
fresh and huge regardless of how deep the caller's recursion is, so the
compiler's guard is once again conservative. One thread is reused for the
process lifetime because walls parse tens of thousands of times.

Exceptions (SyntaxError included) propagate to the caller unchanged.
"""

from __future__ import annotations

import ast
import queue
import threading

__all__ = ["parse_on_big_stack"]

_STACK_BYTES = 64 * 1024 * 1024

_lock = threading.Lock()
_requests: "queue.SimpleQueue[tuple[str, str, queue.SimpleQueue]]" = queue.SimpleQueue()
_worker: threading.Thread | None = None


def _worker_loop() -> None:
    while True:
        source, filename, reply = _requests.get()
        try:
            reply.put((True, ast.parse(source, filename=filename)))
        except BaseException as exc:  # propagate everything, unchanged
            reply.put((False, exc))


def _ensure_worker() -> threading.Thread | None:
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return _worker
        try:
            old = threading.stack_size(_STACK_BYTES)
        except (ValueError, RuntimeError, OverflowError):
            # Platform refuses this stack size: fall back to inline parse.
            return None
        try:
            worker = threading.Thread(
                target=_worker_loop, name="ast-parse-big-stack", daemon=True
            )
            worker.start()
        finally:
            threading.stack_size(old)
        _worker = worker
        return worker


def parse_on_big_stack(source: str, filename: str = "<unknown>") -> ast.Module:
    """`ast.parse(source, filename=filename)` run on a 64 MiB-stack thread.

    Semantically identical to `ast.parse`: same return value, and SyntaxError
    (or any other exception) is re-raised in the caller unchanged. If the
    platform does not support setting a thread stack size, parses inline.
    Never called re-entrantly from the worker itself (the worker only parses).
    """
    if _ensure_worker() is None or threading.current_thread() is _worker:
        return ast.parse(source, filename=filename)
    reply: "queue.SimpleQueue" = queue.SimpleQueue()
    _requests.put((source, filename, reply))
    ok, payload = reply.get()
    if ok:
        return payload
    raise payload
