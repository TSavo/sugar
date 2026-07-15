"""Regression tests for the big-stack `ast.parse` guard.

The lift plugin used to segfault when `ast.parse` was reached with the C
stack already nearly exhausted by deep recursive lift machinery (observed as
`read_line.disconnected` at wandering message ids during pandas/numpy walls,
with faulthandler pointing at ast.parse via leaf_assertions.harvest_source).
`parse_on_big_stack` must succeed where a small-stack thread's plain
`ast.parse` cannot, and must stay semantically identical otherwise.
"""

from __future__ import annotations

import ast
import queue
import sys
import threading

import pytest

from sugar_lift_python_source.big_stack import parse_on_big_stack

# Chained unary minus recurses in the parser without hitting the tokenizer's
# nested-parentheses cap. Depth 2000 is empirically deep enough to SIGSEGV
# plain ast.parse on a 192 KiB-stack thread while parsing fine on a default
# main-thread stack (and trivially on the 64 MiB worker).
_DEPTH = 2000
_DEEP_SOURCE = "-" * _DEPTH + "1"


def _stack_size_supported(size: int) -> bool:
    try:
        old = threading.stack_size(size)
    except (ValueError, RuntimeError, OverflowError):
        return False
    threading.stack_size(old)
    return True


def _run_on_thread_with_stack(size: int, fn) -> tuple[bool, object]:
    """Run fn on a fresh thread with the given stack size; (ok, payload)."""
    out: "queue.SimpleQueue[tuple[bool, object]]" = queue.SimpleQueue()

    def target() -> None:
        try:
            out.put((True, fn()))
        except BaseException as exc:
            out.put((False, exc))

    old = threading.stack_size(size)
    try:
        thread = threading.Thread(target=target)
        thread.start()
    finally:
        threading.stack_size(old)
    thread.join()
    return out.get()


def test_parse_on_big_stack_returns_same_tree_shape() -> None:
    got = parse_on_big_stack("x = 1 + 2\n", "<t>")
    assert ast.dump(got) == ast.dump(ast.parse("x = 1 + 2\n", filename="<t>"))


def test_syntax_error_propagates_unchanged() -> None:
    with pytest.raises(SyntaxError) as exc_info:
        parse_on_big_stack("def broken(:\n", "oops.py")
    assert exc_info.value.filename == "oops.py"


def test_deep_source_parses_where_small_stack_thread_cannot() -> None:
    small = 192 * 1024
    if not _stack_size_supported(small):
        pytest.skip("platform does not support setting a small thread stack")

    # Plain ast.parse on a starved-stack thread must fail. On Linux/CPython
    # this is a hard SIGSEGV (the compiler's recursion guard is tuned for the
    # main thread's stack, not the actual thread stack) -- the exact bug this
    # module fixes -- so run it in a SUBPROCESS and require a nonzero exit.
    # If the subprocess parses it fine, the sentinel is not representative on
    # this platform: skip rather than fail.
    import subprocess

    probe = (
        "import ast, threading, sys\n"
        f"src = {_DEEP_SOURCE!r}\n"
        f"threading.stack_size({small})\n"
        "t = threading.Thread(target=lambda: ast.parse(src))\n"
        "t.start(); t.join()\n"
    )
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True)
    if proc.returncode == 0:
        pytest.skip("small-stack thread parsed the sentinel; not representative")

    # The same source through the big-stack path succeeds, even when invoked
    # FROM the starved thread (the parse itself hops to the big-stack worker).
    ok, payload = _run_on_thread_with_stack(
        small, lambda: parse_on_big_stack(_DEEP_SOURCE, "<deep>")
    )
    assert ok, f"parse_on_big_stack failed: {payload!r}"
    assert isinstance(payload, ast.Module)


def test_reuses_one_worker_thread() -> None:
    parse_on_big_stack("a = 1\n")
    before = {t.name for t in threading.enumerate()}
    for _ in range(50):
        parse_on_big_stack("b = 2\n")
    after = {t.name for t in threading.enumerate()}
    assert before == after
    assert sum(1 for n in after if n == "ast-parse-big-stack") <= 1


def test_harvest_source_uses_guarded_parse() -> None:
    from sugar_lift_python_source.leaf_assertions import harvest_source

    result = harvest_source("def broken(:\n", "oops.py")
    assert any(d.get("kind") == "parse-error" for d in result.diagnostics)
