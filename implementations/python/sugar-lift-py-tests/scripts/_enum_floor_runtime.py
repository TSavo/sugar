"""Shared in-process enum runtime for CI zero-tolerance floors.

One process. One door:

    path_source → SourceFile → functions → sugar

I/O never mixed:
  engine log  → JSONL file (WARNING heartbeats by default; see TRACE)
  progress    → optional tqdm file (local tail)
  job log     → ALWAYS: named phase + running counts (≤30s silence)
  result/print → floor summary lines only

Engine log default is SUGAR_ENGINE_TRACE_EVENTS=0: WARNING heartbeats,
cycle_suspected, and errors only — enough to name a stall. Per-span DEBUG
enter/exit is write-only for floor R (R is the floor axis, not engine.jsonl)
and costs json.dumps+FileHandler on every sugar enter/exit on the reduction
hot path. Set engine_trace=True / SUGAR_ENGINE_TRACE_EVENTS=1 only when
debugging a named stall needs the full flood. Never re-raise the logger to
DEBUG after configure — that made TRACE=0 a no-op (#7039 recensus lesson).

DOCTRINE: if it can run >30s, emit a named phase or count to the JOB LOG
within 30s and every 30s after. TTY-gated tqdm and file-only progress are
identical to none in Actions.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence, TextIO, TypeVar

T = TypeVar("T")

# Repo tools/ is not always on path when floors run as scripts/.
_TOOLS = Path(__file__).resolve().parents[4] / "tools"
if _TOOLS.is_dir() and str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))


def silence_console_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(logging.NullHandler())
    root.setLevel(logging.CRITICAL)
    logging.lastResort = None  # type: ignore[assignment]


def configure_engine_log(path: Path, *, engine_trace: bool = False) -> None:
    """Attach engine JSONL for stall-naming; default TRACE off.

    Default is WARNING-only (``SUGAR_ENGINE_TRACE_EVENTS=0``): heartbeats,
    cycle_suspected, and errors. Per-span DEBUG enter/exit is opt-in via
    ``engine_trace=True`` — floor axes do not read those events for R, and
    they pay ``json.dumps`` on the reduction hot path.

    Critical: do **not** re-raise ``LOGGER`` to DEBUG after
    ``configure_live_log``. Handler-only WARNING still serialises every
    DEBUG span before the record is dropped; logger level must follow TRACE
    so ``isEnabledFor(DEBUG)`` short-circuits. Same lesson as recensus #7039
    (43% wall-time cut on scoreboard from killing this flood).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["SUGAR_ENGINE_LOG"] = str(path.resolve())
    # Force measurement default: do not inherit ambient TRACE=1. Full span
    # flood is explicit engine_trace only.
    os.environ["SUGAR_ENGINE_TRACE_EVENTS"] = "1" if engine_trace else "0"
    from sugar_lift_py_tests import engine_log

    logger = engine_log.LOGGER
    logger.handlers.clear()
    logger.propagate = False
    engine_log._LIVE_HANDLER = None  # type: ignore[attr-defined]
    engine_log.configure_live_log(str(path.resolve()))
    logger.propagate = False
    # configure_live_log already set level from TRACE. Pin it again so a
    # future editor cannot reintroduce setLevel(DEBUG) and re-enable the flood.
    logger.setLevel(logging.DEBUG if engine_trace else logging.WARNING)


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
    """Kit package + corpus tooling only — NOT the pandas/numpy corpus wall.

    Historical trap: native-crash / timeout / bare-exception floors defaulted
    here when invoked with no path args. That measures Sugar's own sources
    (~400 files) and reports green while the authenticated pandas corpus
    (the population those process floors police) stays unmeasured. Use this
    helper only when the caller *names* kit self-check; never as a silent
    CLI default for corpus process floors.
    """
    kit = repo_root / "implementations/python/sugar-lift-py-tests"
    return (kit / "src/sugar_lift_py_tests", kit / "scripts")


def require_python_paths(roots: Sequence[Path]) -> list[Path]:
    paths = python_paths(roots)
    if not paths:
        raise ValueError(f"no Python source files found under {list(roots)}")
    return paths


def add_lpt_shard_args(parser) -> None:
    """CLI for LPT file sharding (k=8 default; same key as suite)."""
    parser.add_argument(
        "--shard-index",
        type=int,
        default=None,
        help="0-based LPT/equal-count file shard (omit = full population)",
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=8,
        help="file shard count k (default 8; do not raise without env evidence)",
    )


def add_demand_table_arg(parser) -> None:
    """Expose the authenticated shared demand-table entrance on process floors."""
    parser.add_argument(
        "--demand-table-path",
        type=Path,
        default=None,
        help=(
            "authenticated python-demand-table JSON; omission is an immediate "
            "UNMEASURED refusal, never local demand derivation"
        ),
    )


def require_demand_table(path: Path | None) -> Path:
    """Refuse before scanning when the authenticated table was not supplied."""
    if path is None:
        raise ValueError(
            "authenticated python-demand-table is required; refusing local "
            "demand derivation (pass --demand-table-path)"
        )
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(
            "authenticated python-demand-table is not a file: "
            f"{resolved}; refusing local demand derivation"
        )
    return resolved


def apply_lpt_file_shard(
    paths: Sequence[Path],
    *,
    root: Path,
    shard_index: int | None,
    shard_count: int,
    population: str,
) -> list[Path]:
    """Filter paths to one LPT shard; no-op when shard_index is None."""
    if shard_index is None:
        return list(paths)
    if not (0 <= shard_index < shard_count):
        raise ValueError(
            f"shard_index {shard_index} out of range for shard_count {shard_count}"
        )
    # Process-floor coverage is a measurement invariant, not a scheduling
    # optimisation.  A per-axis LPT prior can produce different assignments
    # when shards receive different prior shelves, leaving omissions and
    # duplicates across the matrix.  Use the showcase law: one canonical
    # lexical roster, ordinal modulo k.  LPT remains available to package
    # suite callers where balance is the objective.
    ordered = sorted({p.resolve() for p in paths}, key=lambda p: p.relative_to(root).as_posix())
    return [p for ordinal, p in enumerate(ordered) if ordinal % shard_count == shard_index]


def require_explicit_scan_roots(roots: Sequence[Path]) -> list[Path]:
    """Refuse empty path sets so a floor cannot green on a defaulted population.

    The silent ``production_roots`` argparse default was a false-green door:
    CI invoked the scanners with no args, they scanned kit src+scripts, and
    R=0 meant "kit did not crash" while the pandas corpus was never entered.

    Call sites must pass the intended roots (authenticated pandas corpus for
    process floors). Empty is red, not a fallback.

    Retirement: when these scanners' CLIs no longer admit zero path args
    (required non-empty roots at the argparse door / typed config), delete
    this check — empty becomes unrepresentable rather than audited.
    """
    if not roots:
        raise ValueError(
            "scan roots must be explicit and non-empty; refusing empty or "
            "defaulted path set (wrong-population false green). Pass the "
            "authenticated pandas corpus root (or other named population), "
            "never rely on production_roots as a silent default."
        )
    return require_python_paths(roots)


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
    progress: TextIO | None = None,
    total: int | None = None,
    initial: int = 0,
    desc: str = "enum",
    progress_stdout: bool = False,
) -> Iterator[T]:
    """Yield items with optional file tqdm AND always-on job-log heartbeats.

    ``progress_stdout`` only controls an *extra* interactive tqdm on stderr when
    a TTY is present. Job-log lines are never TTY-gated and never optional —
    CI is not a TTY and file-only tqdm was the silent wedge.
    """
    from job_log_heartbeat import JobLogHeartbeat  # noqa: WPS433 — scripts path

    n_total = total if total is not None else len(items)
    beat = JobLogHeartbeat(desc, total=n_total)
    beat.n = initial
    beat.watch()

    bar = None
    live = None
    if progress is not None:
        try:
            from tqdm import tqdm
        except ImportError as error:  # pragma: no cover
            raise SystemExit(
                "tqdm is required: python3 -m pip install 'tqdm>=4.66'"
            ) from error

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
        # Interactive TTY only — never the sole progress channel.
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
        iterator: Any = bar
    else:
        iterator = items

    done = initial
    try:
        for item in iterator:
            yield item
            done += 1
            # Running counts as they accumulate (not only at the end).
            beat.tick(n=done, force=(done == n_total or done == initial + 1))
            if live is not None:
                live.update(1)
                if bar is not None and getattr(bar, "postfix", None):
                    live.set_postfix_str(str(bar.postfix), refresh=False)
    finally:
        beat.stop(status="end")
        if bar is not None:
            bar.close()
        if live is not None:
            live.close()
        if progress is not None:
            progress.flush()


def floor_workspace_root() -> Path:
    """Writable workspace for floor scratch — never the scan population.

    Population roots (authenticated pandas under site-packages) are read-only
    vendor trees. Scratch under that root mutates the thing being measured and
    fails when the tree is not writable (S0.2 / run 30727525884).

    Prefer explicit SUGAR_FLOOR_WORKSPACE, then CI workspace/tmp env, else
    process temp. Callers may still pass --out-dir; that path is still checked
    against the population root and refused if nested under it.
    """
    for key in ("SUGAR_FLOOR_WORKSPACE", "GITHUB_WORKSPACE", "RUNNER_TEMP"):
        raw = os.environ.get(key)
        if raw:
            return Path(raw)
    return Path(tempfile.gettempdir()) / "sugar-floor-workspace"


def default_out_dir(repo_root: Path, floor: str) -> Path:
    """Scratch directory for one floor. ``repo_root`` is the population root.

    Historically this returned ``repo_root / .sugar / ci-floors / floor``, which
    wrote into vendor site-packages when --repo-root was the pandas corpus.
    Scratch is always under floor_workspace_root(); population is never the base.
    """
    del repo_root  # population root must not host scratch
    return floor_workspace_root() / ".sugar" / "ci-floors" / floor


def _is_path_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def prepare_floor_io(
    *,
    repo_root: Path,
    floor: str,
    out_dir: Path | None,
    engine_log: Path | None,
    progress: Path | None,
) -> tuple[Path, Path, Path]:
    """Open engine/progress logs under workspace scratch, not the population.

    ``repo_root`` is the population root (relative loci / corpus). Scratch must
    never nest under it — even when mkdir would succeed, mutating a vendor
    corpus is wrong.
    """
    population = repo_root
    base = out_dir or default_out_dir(repo_root, floor)
    if _is_path_under(base, population):
        raise ValueError(
            "floor scratch must not live under the population root "
            f"(population={population}, scratch={base}). "
            "Pass --out-dir under a workspace/tmp path, or set "
            "SUGAR_FLOOR_WORKSPACE / GITHUB_WORKSPACE / RUNNER_TEMP."
        )
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise OSError(
            f"floor scratch mkdir failed under workspace path {base}: {error}. "
            "Scratch is never under the population; check workspace permissions."
        ) from error
    engine_path = engine_log or (base / "engine.jsonl")
    progress_path = progress or (base / "progress.log")
    if _is_path_under(engine_path, population) or _is_path_under(
        progress_path, population
    ):
        raise ValueError(
            "engine/progress paths must not live under the population root "
            f"(population={population})."
        )
    silence_console_logging()
    configure_engine_log(engine_path)
    return base, engine_path, progress_path


def format_completed_axis_report(axis: str, r_value: int) -> str:
    """Print R only after a completed measurement. Never invent a zero.

    Incomplete / crashed floors must use :func:`format_unmeasured_axis` so a
    reader cannot bank ``R_axis = 0`` that was never taken.
    """
    return f"{axis} = {r_value}"


def format_unmeasured_axis(axis: str, *, reason: str) -> str:
    """Lease-gate vocabulary: unmeasured / completed-with-error / no-value.

    Deliberately does **not** contain the substring ``{axis} = 0`` or bare
    `` = 0`` — readers (and greps) bank that pattern as a completed zero.
    """
    return (
        f"{axis}: unmeasured "
        f"(status=completed-with-error; reason={reason!r}; value=no-value). "
        f"Measurement did not complete; residual is not a completed zero."
    )

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
