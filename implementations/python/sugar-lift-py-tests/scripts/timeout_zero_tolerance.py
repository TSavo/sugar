#!/usr/bin/env python3
"""R_timeouts — permanent baseline-free bounded-termination floor.

Supervised persistent enum worker. A file exceeding the wall clock kills only
that worker (caches restart); the file is a timeout offender and the scan continues.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import NamedTuple, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _enum_floor_runtime import (  # noqa: E402
    prepare_floor_io,
    production_roots,
    require_python_paths,
)
from _production_lift_child import production_lift_bootstrap_error  # noqa: E402
from _supervised_enum_supervisor import FileTerminal, scan_paths  # noqa: E402


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


def _from_terminal(row: FileTerminal, *, file_timeout: float) -> ChildResult:
    if row.category == "timeout":
        return ChildResult(
            row.file,
            "timeout",
            timeout_offender(file=row.file, timeout_seconds=file_timeout),
        )
    return ChildResult(row.file, row.category, None)


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
    del workers, checkpoint_path, progress_stdout
    if file_timeout > 30:
        raise ValueError("per-file timeout may not exceed 30 seconds")
    terminals = scan_paths(paths, root=root, file_timeout=float(file_timeout))
    if progress_path is not None:
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        with progress_path.open("w", encoding="utf-8") as stream:
            stream.write(f"# timeout supervised enum scan files={len(paths)}\n")
            for t in terminals:
                stream.write(f"{t.file}\t{t.category}\n")
    rows = tuple(
        _from_terminal(t, file_timeout=float(file_timeout)) for t in terminals
    )
    return AuditSummary(
        rows=rows,
        offenders=tuple(row.offender for row in rows if row.offender is not None),
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
        progress_path=progress_path,
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
                "typedGaps": sum(row.category == "typed-gap" for row in rows),
                "nativeCrashes": sum(row.category == "native-crash" for row in rows),
                "bareExceptions": sum(
                    row.category == "bare-exception" for row in rows
                ),
            },
            measured=True,
        )
        write_json(args.json, payload)
    print(
        "TIMEOUT SURFACE: "
        f"discovered={len(rows)} "
        f"completed={sum(row.category == 'completed' for row in rows)} "
        f"typed_gaps={sum(row.category == 'typed-gap' for row in rows)} "
        f"timeouts={len(offenders)} "
        f"progress={progress_path} engine={engine_path}"
    )
    print(f"R_timeouts = {len(offenders)}")
    for row in offenders:
        print(f"{row.file}:timeout>{row.timeout_seconds}s")
    return 1 if offenders else 0


if __name__ == "__main__":
    raise SystemExit(main())
