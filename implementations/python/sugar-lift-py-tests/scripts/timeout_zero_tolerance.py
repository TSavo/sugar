#!/usr/bin/env python3
"""R_timeouts — permanent baseline-free bounded-termination floor.

In-process enum door. Per-file wall clock via SIGALRM (same process — caches
stay warm). Progress and engine logs never mix.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any, Mapping, NamedTuple, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _enum_floor_runtime import (  # noqa: E402
    iter_with_tqdm,
    open_progress,
    prepare_floor_io,
    production_roots,
    relative_to_root,
    require_python_paths,
    timed_enum_file,
)
from _production_lift_child import production_lift_bootstrap_error  # noqa: E402


class TimeoutOffender(NamedTuple):
    file: str
    timeout_seconds: float


class ChildResult(NamedTuple):
    file: str
    category: str
    offender: TimeoutOffender | None


class AuditSummary(NamedTuple):
    rows: tuple[ChildResult, ...]
    offenders: tuple[TimeoutOffender, ...]


def timeout_offender(*, file: str, timeout_seconds: float) -> TimeoutOffender:
    return TimeoutOffender(file, timeout_seconds)


def r_timeouts(offenders: Sequence[TimeoutOffender]) -> int:
    return len(offenders)


def _run_one(path: Path, *, root: Path, file_timeout: int) -> ChildResult:
    rel, _testimony, error, _s = timed_enum_file(
        path, root=root, file_timeout=file_timeout
    )
    if isinstance(error, TimeoutError):
        return ChildResult(
            rel,
            "timeout",
            timeout_offender(file=rel, timeout_seconds=float(file_timeout)),
        )
    if error is not None:
        return ChildResult(rel, "non-native-red", None)
    return ChildResult(rel, "completed", None)


def audit_paths(
    paths: Sequence[Path],
    *,
    root: Path,
    file_timeout: int,
    workers: int = 1,
    checkpoint_path: Path | None = None,
    progress_path: Path | None = None,
    progress_stdout: bool = False,
) -> AuditSummary:
    del workers  # always single-process
    if file_timeout > 30:
        raise ValueError("per-file timeout may not exceed 30 seconds")

    pending = list(sorted(paths))
    done_rows: dict[str, ChildResult] = {}

    if checkpoint_path is not None:
        from pandas_census_checkpoint import Checkpoint

        files = tuple(relative_to_root(p, root) for p in pending)
        by_rel = {relative_to_root(p, root): p for p in pending}
        checkpoint = Checkpoint(
            floor="timeout", files=files, path=checkpoint_path
        )
        for row in checkpoint.rows():
            raw = row["result"]
            file = str(row["file"])
            seconds = raw.get("timeoutSeconds")
            offender = (
                timeout_offender(file=file, timeout_seconds=float(seconds))
                if raw.get("category") == "timeout"
                and isinstance(seconds, (int, float))
                else None
            )
            done_rows[file] = ChildResult(file, str(raw.get("category")), offender)
        pending_rels = list(checkpoint.pending_files())
        pending = [by_rel[r] for r in pending_rels]
    else:
        checkpoint = None
        by_rel = {}

    progress_stream = None
    if progress_path is not None:
        progress_stream = open_progress(
            progress_path,
            header=(
                f"# timeout floor (in-process enum)\n"
                f"# files={len(paths)} pending={len(pending)}\n"
            ),
        )

    try:
        iterator: Sequence[Path] | Any = pending
        if progress_stream is not None:
            iterator = iter_with_tqdm(
                pending,
                progress=progress_stream,
                total=len(paths),
                initial=len(paths) - len(pending),
                desc="timeout",
                progress_stdout=progress_stdout,
            )
        for path in iterator:
            row = _run_one(path, root=root, file_timeout=file_timeout)
            if checkpoint is not None:
                checkpoint.append(
                    row.file,
                    {
                        "category": row.category,
                        "timeoutSeconds": (
                            row.offender.timeout_seconds if row.offender else None
                        ),
                    },
                )
            done_rows[row.file] = row
    finally:
        if progress_stream is not None:
            progress_stream.close()

    if checkpoint is not None:
        ordered = tuple(
            done_rows[f] if f in done_rows else ChildResult(f, "missing", None)
            for f in checkpoint.files
        )
    else:
        ordered = tuple(
            done_rows[relative_to_root(p, root)] for p in sorted(paths)
        )
    return AuditSummary(
        rows=ordered,
        offenders=tuple(row.offender for row in ordered if row.offender is not None),
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
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--checkpoint-jsonl", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--engine-log", type=Path, default=None)
    parser.add_argument("--progress", type=Path, default=None)
    parser.add_argument("--progress-stdout", action="store_true")
    args = parser.parse_args()

    boot_error = production_lift_bootstrap_error()
    if boot_error is not None:
        print(
            "TIMEOUT SCANNER INFRASTRUCTURE FAILURE: the production "
            f"lift door did not bootstrap: {boot_error}"
        )
        return 2
    try:
        paths = require_python_paths(args.paths)
    except ValueError as error:
        print(f"TIMEOUT ZERO-TOLERANCE RED: {error}")
        return 1

    _base, engine_path, progress_path = prepare_floor_io(
        repo_root=args.repo_root,
        floor="timeout",
        out_dir=args.out_dir,
        engine_log=args.engine_log,
        progress=args.progress,
    )
    summary = audit_paths(
        paths,
        root=args.repo_root,
        file_timeout=args.file_timeout,
        workers=1,
        checkpoint_path=args.checkpoint_jsonl,
        progress_path=progress_path,
        progress_stdout=args.progress_stdout,
    )
    rows = summary.rows
    offenders = summary.offenders
    if args.json is not None:
        from pandas_floor_summary import floor_summary, relative_files, write_json

        files = relative_files(paths, args.repo_root)
        payload = floor_summary(
            floor="timeout",
            files=files,
            rows=[
                {
                    "file": row.file,
                    "category": row.category,
                    "timeoutSeconds": (
                        row.offender.timeout_seconds if row.offender else None
                    ),
                }
                for row in rows
            ],
            totals={
                "R_timeouts": len(offenders),
                "completed": sum(row.category == "completed" for row in rows),
                "nativeCrashes": sum(row.category == "native-crash" for row in rows),
                "nonNativeRed": sum(row.category == "non-native-red" for row in rows),
            },
            measured=True,
        )
        write_json(args.json, payload)
    print(
        "TIMEOUT SURFACE: "
        f"discovered={len(rows)} "
        f"completed={sum(row.category == 'completed' for row in rows)} "
        f"non_native_red={sum(row.category == 'non-native-red' for row in rows)} "
        f"timeouts={len(offenders)} "
        f"progress={progress_path} engine={engine_path}"
    )
    print(f"R_timeouts = {len(offenders)}")
    for row in offenders:
        print(f"{row.file}:timeout>{row.timeout_seconds}s")
    return 1 if offenders else 0


if __name__ == "__main__":
    raise SystemExit(main())
