#!/usr/bin/env python3
"""R_native_crashes — permanent baseline-free corpus process floor.

In-process enum scan. A true signal death still kills the whole process (CI
goes red). Per-file signal isolation is retired — process restarts destroy
enum caches. Classification helpers remain for discrimination tests.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import sys
from typing import Any, NamedTuple, Sequence

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


class NativeCrashOffender(NamedTuple):
    file: str
    returncode: int
    signal: str
    stderr_tail: str


class ChildResult(NamedTuple):
    file: str
    category: str
    returncode: int | None
    stderr_tail: str
    offender: NativeCrashOffender | None


class AuditSummary(NamedTuple):
    discovered: int
    completed: int
    timeouts: int
    non_native_red: int
    offenders: tuple[NativeCrashOffender, ...]
    rows: tuple[ChildResult, ...]


def native_crash_offender(
    *, file: str, returncode: int, stderr: str
) -> NativeCrashOffender | None:
    if returncode >= 0:
        return None
    signal_number = -returncode
    try:
        signal_name = signal.Signals(signal_number).name
    except ValueError:
        signal_name = f"signal-{signal_number}"
    return NativeCrashOffender(
        file=file,
        returncode=returncode,
        signal=signal_name,
        stderr_tail=stderr[-2000:],
    )


def r_native_crashes(offenders: Sequence[NativeCrashOffender]) -> int:
    return len(offenders)


def format_report(offenders: Sequence[NativeCrashOffender]) -> str:
    lines = [
        f"R_native_crashes = {r_native_crashes(offenders)}",
        (
            "Replacement: corpus enumeration terminates with completed testimony, "
            "typed gap, bare-exception row, or loud timeout; never signal."
        ),
        "",
        "Loci:",
    ]
    for row in offenders:
        lines.append(f"{row.file}:returncode={row.returncode}:signal={row.signal}")
        if row.stderr_tail:
            lines.append(row.stderr_tail)
    return "\n".join(lines)


def _run_one(path: Path, *, root: Path, file_timeout: int) -> ChildResult:
    rel, _testimony, error, _s = timed_enum_file(
        path, root=root, file_timeout=file_timeout
    )
    if isinstance(error, TimeoutError):
        return ChildResult(rel, "timeout", None, str(error), None)
    if error is not None:
        return ChildResult(
            rel,
            "non-native-red",
            1,
            f"{type(error).__name__}: {error}"[-2000:],
            None,
        )
    # Process survived this file — no per-file native crash without isolation.
    return ChildResult(rel, "completed", 0, "", None)


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
    del workers
    if file_timeout > 30:
        raise ValueError("per-file timeout may not exceed 30 seconds")

    pending = list(sorted(paths))
    done_rows: dict[str, ChildResult] = {}
    checkpoint = None
    if checkpoint_path is not None:
        from pandas_census_checkpoint import Checkpoint

        files = tuple(relative_to_root(p, root) for p in pending)
        by_rel = {relative_to_root(p, root): p for p in pending}
        checkpoint = Checkpoint(
            floor="native-crash", files=files, path=checkpoint_path
        )
        for row in checkpoint.rows():
            raw = row["result"]
            file = str(row["file"])
            returncode = raw.get("returncode")
            code = int(returncode) if isinstance(returncode, int) else None
            stderr_tail = str(raw.get("stderrTail") or "")
            signal_name = raw.get("signal")
            offender = (
                NativeCrashOffender(file, code, str(signal_name), stderr_tail)
                if raw.get("category") == "native-crash"
                and code is not None
                and isinstance(signal_name, str)
                else None
            )
            done_rows[file] = ChildResult(
                file, str(raw.get("category")), code, stderr_tail, offender
            )
        pending = [by_rel[r] for r in checkpoint.pending_files()]

    progress_stream = None
    if progress_path is not None:
        progress_stream = open_progress(
            progress_path,
            header=(
                f"# native-crash floor (in-process enum)\n"
                f"# files={len(paths)} pending={len(pending)}\n"
            ),
        )
    try:
        iterator: Any = pending
        if progress_stream is not None:
            iterator = iter_with_tqdm(
                pending,
                progress=progress_stream,
                total=len(paths),
                initial=len(paths) - len(pending),
                desc="native-crash",
                progress_stdout=progress_stdout,
            )
        for path in iterator:
            row = _run_one(path, root=root, file_timeout=file_timeout)
            if checkpoint is not None:
                checkpoint.append(
                    row.file,
                    {
                        "category": row.category,
                        "returncode": row.returncode,
                        "stderrTail": row.stderr_tail,
                        "signal": row.offender.signal if row.offender else None,
                    },
                )
            done_rows[row.file] = row
    finally:
        if progress_stream is not None:
            progress_stream.close()

    if checkpoint is not None:
        rows = tuple(
            done_rows[f]
            if f in done_rows
            else ChildResult(f, "missing", None, "", None)
            for f in checkpoint.files
        )
    else:
        rows = tuple(
            done_rows[relative_to_root(p, root)] for p in sorted(paths)
        )
    offenders = tuple(row.offender for row in rows if row.offender is not None)
    return AuditSummary(
        discovered=len(rows),
        completed=sum(row.category == "completed" for row in rows),
        timeouts=sum(row.category == "timeout" for row in rows),
        non_native_red=sum(row.category == "non-native-red" for row in rows),
        offenders=offenders,
        rows=rows,
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
        "paths",
        nargs="*",
        type=Path,
        default=list(production_roots(repo_root)),
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
            "NATIVE-CRASH SCANNER INFRASTRUCTURE FAILURE: the production "
            f"lift door did not bootstrap: {boot_error}"
        )
        return 2

    try:
        paths = require_python_paths(args.paths)
    except ValueError as error:
        print(f"NATIVE-CRASH ZERO-TOLERANCE RED: {error}")
        return 1

    _base, engine_path, progress_path = prepare_floor_io(
        repo_root=args.repo_root,
        floor="native-crash",
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
    if args.json is not None:
        from pandas_floor_summary import floor_summary, relative_files, write_json

        files = relative_files(paths, args.repo_root)
        payload = floor_summary(
            floor="native-crash",
            files=files,
            rows=[
                {
                    "file": row.file,
                    "category": row.category,
                    "returncode": row.returncode,
                    "signal": row.offender.signal if row.offender else None,
                }
                for row in summary.rows
            ],
            totals={
                "R_native_crashes": len(summary.offenders),
                "completed": summary.completed,
                "timeouts": summary.timeouts,
                "nonNativeRed": summary.non_native_red,
            },
            measured=True,
        )
        write_json(args.json, payload)
    print(
        "NATIVE-CRASH SURFACE: "
        f"discovered={summary.discovered} completed={summary.completed} "
        f"timeouts={summary.timeouts} non_native_red={summary.non_native_red} "
        f"progress={progress_path} engine={engine_path}"
    )
    print(format_report(summary.offenders))
    return 1 if summary.offenders else 0


if __name__ == "__main__":
    raise SystemExit(main())
