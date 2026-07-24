"""Shared in-process enum runtime for CI zero-tolerance floors.

One process. One door:

    path_source → SourceFile → functions → sugar

I/O never mixed:
  engine log  → JSONL file (sugar construction telemetry)
  progress    → tqdm only
  result/print → floor summary lines only
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence, TextIO, TypeVar

T = TypeVar("T")


def silence_console_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(logging.NullHandler())
    root.setLevel(logging.CRITICAL)
    logging.lastResort = None  # type: ignore[assignment]


def configure_engine_log(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["SUGAR_ENGINE_LOG"] = str(path.resolve())
    from sugar_lift_py_tests import engine_log

    logger = engine_log.LOGGER
    logger.handlers.clear()
    logger.propagate = False
    engine_log._LIVE_HANDLER = None  # type: ignore[attr-defined]
    engine_log.configure_live_log(str(path.resolve()))
    logger.propagate = False
    logger.setLevel(logging.DEBUG)


def python_paths(roots: Sequence[Path]) -> list[Path]:
    return sorted(
        {
            path
            for root in roots
            for path in (root.rglob("*.py") if root.is_dir() else (root,))
            if path.is_file() and "__pycache__" not in path.parts
        }
    )


def production_roots(repo_root: Path) -> tuple[Path, Path]:
    kit = repo_root / "implementations/python/sugar-lift-py-tests"
    return (kit / "src/sugar_lift_py_tests", kit / "scripts")


def require_python_paths(roots: Sequence[Path]) -> list[Path]:
    paths = python_paths(roots)
    if not paths:
        raise ValueError(f"no Python source files found under {list(roots)}")
    return paths


def relative_to_root(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def enum_lift_testimony(path: Path, rel: str) -> dict[str, object]:
    """Lift one file through the enum production door (in-process)."""
    from _production_lift_child import production_lift_testimony

    return production_lift_testimony(path, rel)


def with_file_timeout(seconds: int, fn: Callable[[], T]) -> T:
    """Bound one file in-process. SIGALRM — same process, caches stay warm."""
    if seconds <= 0:
        return fn()
    if not hasattr(signal, "SIGALRM"):
        return fn()

    def _on_alarm(_signum, _frame) -> None:
        raise TimeoutError(f"file timeout after {seconds}s")

    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous)


def open_progress(path: Path, *, header: str) -> TextIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("w", encoding="utf-8")
    stream.write(header if header.endswith("\n") else header + "\n")
    stream.flush()
    return stream


def iter_with_tqdm(
    items: Sequence[T],
    *,
    progress: TextIO,
    total: int | None = None,
    initial: int = 0,
    desc: str = "enum",
    progress_stdout: bool = False,
) -> Iterator[T]:
    try:
        from tqdm import tqdm
    except ImportError as error:  # pragma: no cover
        raise SystemExit(
            "tqdm is required: python3 -m pip install 'tqdm>=4.66'"
        ) from error

    n_total = total if total is not None else len(items)
    bar = tqdm(
        items,
        total=n_total,
        initial=initial,
        unit="file",
        desc=desc,
        file=progress,
        dynamic_ncols=False,
        ncols=120,
        mininterval=0.2,
        smoothing=0.05,
        bar_format=(
            "{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, "
            "{rate_fmt}] {postfix}"
        ),
    )
    live = None
    if progress_stdout and sys.stderr.isatty():
        live = tqdm(
            total=n_total,
            initial=initial,
            unit="file",
            desc=desc,
            file=sys.stderr,
            dynamic_ncols=True,
            mininterval=0.2,
            smoothing=0.05,
            bar_format=(
                "{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, "
                "{rate_fmt}] {postfix}"
            ),
        )
    try:
        for item in bar:
            yield item
            if live is not None:
                live.update(1)
                # Keep live postfix in sync when caller sets on bar.
                if getattr(bar, "postfix", None):
                    live.set_postfix_str(str(bar.postfix), refresh=False)
    finally:
        bar.close()
        if live is not None:
            live.close()
        progress.flush()


def default_out_dir(repo_root: Path, floor: str) -> Path:
    return repo_root / ".sugar" / "ci-floors" / floor


def prepare_floor_io(
    *,
    repo_root: Path,
    floor: str,
    out_dir: Path | None,
    engine_log: Path | None,
    progress: Path | None,
) -> tuple[Path, Path, Path]:
    base = out_dir or default_out_dir(repo_root, floor)
    base.mkdir(parents=True, exist_ok=True)
    engine_path = engine_log or (base / "engine.jsonl")
    progress_path = progress or (base / "progress.log")
    silence_console_logging()
    configure_engine_log(engine_path)
    return base, engine_path, progress_path


def timed_enum_file(
    path: Path,
    *,
    root: Path,
    file_timeout: int,
) -> tuple[str, dict[str, object] | None, BaseException | None, float]:
    """Returns (rel, testimony|None, error|None, seconds)."""
    rel = relative_to_root(path, root)
    t0 = time.perf_counter()
    try:

        def _lift() -> dict[str, object]:
            return enum_lift_testimony(path, rel)

        testimony = with_file_timeout(file_timeout, _lift)
        return rel, testimony, None, time.perf_counter() - t0
    except TimeoutError as error:
        return rel, None, error, time.perf_counter() - t0
    # ConstructionPanic is BaseException: must not be held here. It kills the
    # process; the supervisor records the in-flight file as a loud terminal.
    except Exception as error:  # bare Python failures only
        return rel, None, error, time.perf_counter() - t0
