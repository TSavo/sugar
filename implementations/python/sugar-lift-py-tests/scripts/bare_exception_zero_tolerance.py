#!/usr/bin/env python3
"""R_bare_exceptions — permanent baseline-free untyped-failure floor.

In-process enum door (path_source → SourceFile → functions → sugar).
One process for the whole scan — caches stay warm.
Progress → progress.log; engine JSONL → engine.jsonl; never mixed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, NamedTuple, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _enum_floor_runtime import (  # noqa: E402
    iter_with_tqdm,
    open_progress,
    prepare_floor_io,
    production_roots,
    require_python_paths,
    timed_enum_file,
)

# Re-export for discrimination tests / external importers.
__all__ = [
    "BareExceptionOffender",
    "bare_exception_offender",
    "production_roots",
    "r_bare_exceptions",
    "require_python_paths",
]
from _production_lift_child import (  # noqa: E402
    NON_FAILURE_OUTCOMES,
    OUTCOME_COMPLETED,
    OUTCOME_TYPED_GAP,
    production_lift_bootstrap_error,
)


class BareExceptionOffender(NamedTuple):
    file: str
    returncode: int
    stderr_tail: str


class ChildResult(NamedTuple):
    file: str
    category: str
    offender: BareExceptionOffender | None


def _terminal(stdout: str) -> Mapping[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, Mapping) and row.get("kind") == "lift-terminal":
            return row
    return None


def bare_exception_offender(
    *, file: str, result: subprocess.CompletedProcess[str]
) -> BareExceptionOffender | None:
    """Classifier for subprocess-shaped results (discrimination tests)."""
    if result.returncode < 0:
        return None
    testimony = _terminal(result.stdout)
    if testimony is not None and testimony.get("outcome") in NON_FAILURE_OUTCOMES:
        return None
    if result.returncode == 0:
        return None
    return BareExceptionOffender(file, result.returncode, result.stderr[-2000:])


def r_bare_exceptions(offenders: Sequence[BareExceptionOffender]) -> int:
    return len(offenders)


def _classify_in_process(
    rel: str,
    testimony: dict[str, object] | None,
    error: BaseException | None,
) -> ChildResult:
    if error is not None:
        if isinstance(error, TimeoutError):
            return ChildResult(rel, "timeout", None)
        # Typed gaps are caught inside production_lift_testimony; anything else
        # that escapes is a bare untyped failure.
        return ChildResult(
            rel,
            "bare-exception",
            BareExceptionOffender(
                rel,
                1,
                f"{type(error).__name__}: {error}"[-2000:],
            ),
        )
    assert testimony is not None
    outcome = str(testimony.get("outcome") or "")
    if outcome in NON_FAILURE_OUTCOMES:
        return ChildResult(rel, outcome, None)
    return ChildResult(
        rel,
        "bare-exception",
        BareExceptionOffender(rel, 1, f"unexpected outcome {outcome!r}"),
    )


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    repo_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="*", type=Path, default=list(production_roots(repo_root))
    )
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    parser.add_argument("--file-timeout", type=int, default=30)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--engine-log", type=Path, default=None)
    parser.add_argument("--progress", type=Path, default=None)
    parser.add_argument("--progress-stdout", action="store_true")
    # Kept for CI flag compatibility; scan is always single-process.
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    del args.workers

    boot_error = production_lift_bootstrap_error()
    if boot_error is not None:
        print(
            "BARE-EXCEPTION SCANNER INFRASTRUCTURE FAILURE: the production lift "
            f"door did not bootstrap: {boot_error}"
        )
        return 2
    try:
        paths = require_python_paths(args.paths)
    except ValueError as error:
        print(f"BARE-EXCEPTION ZERO-TOLERANCE RED: {error}")
        return 1

    _base, engine_path, progress_path = prepare_floor_io(
        repo_root=args.repo_root,
        floor="bare-exception",
        out_dir=args.out_dir,
        engine_log=args.engine_log,
        progress=args.progress,
    )
    progress = open_progress(
        progress_path,
        header=(
            f"# bare-exception floor (in-process enum)\n"
            f"# engine_log={engine_path.resolve()}\n"
            f"# files={len(paths)}\n"
        ),
    )
    rows: list[ChildResult] = []
    try:
        for path in iter_with_tqdm(
            paths,
            progress=progress,
            desc="bare-exception",
            progress_stdout=args.progress_stdout,
        ):
            rel, testimony, error, file_s = timed_enum_file(
                path, root=args.repo_root, file_timeout=args.file_timeout
            )
            row = _classify_in_process(rel, testimony, error)
            rows.append(row)
            del file_s  # timed for future postfix hooks; bar shows rate already
    finally:
        progress.close()

    offenders = tuple(row.offender for row in rows if row.offender is not None)
    print(
        "BARE-EXCEPTION SURFACE: "
        f"discovered={len(rows)} "
        f"completed={sum(row.category == OUTCOME_COMPLETED for row in rows)} "
        f"typed_gaps={sum(row.category == OUTCOME_TYPED_GAP for row in rows)} "
        f"timeouts={sum(row.category == 'timeout' for row in rows)} "
        f"bare={len(offenders)} "
        f"progress={progress_path} engine={engine_path}"
    )
    print(f"R_bare_exceptions = {len(offenders)}")
    for row in offenders:
        tail = (row.stderr_tail.splitlines() or ["no detail"])[-1]
        print(f"{row.file}:returncode={row.returncode}:bare-exception — {tail}")
    return 1 if offenders else 0


if __name__ == "__main__":
    raise SystemExit(main())
