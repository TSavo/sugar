#!/usr/bin/env python3
"""R_native_crashes — permanent baseline-free corpus process floor.

Supervised persistent enum worker. A signal death is attributed to the file
currently in flight; the worker restarts and the census continues so every
file still gets a terminal row.
"""

from __future__ import annotations

# Not the board. This module measures its own named denominator; the sole
# authoritative Python corpus scoreboard is scripts/control_effect_recensus.py.
# See tests/test_one_authoritative_scoreboard.py.
SCOREBOARD_AUTHORITY = False

import argparse
import os
from pathlib import Path
import signal
import sys
from typing import NamedTuple, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _enum_floor_runtime import (  # noqa: E402
    format_completed_axis_report,
    format_unmeasured_axis,
    prepare_floor_io,
    production_roots,
    require_explicit_scan_roots,
    require_python_paths,
)
from _production_lift_child import production_lift_bootstrap_error  # noqa: E402
from _supervised_enum_supervisor import FileTerminal, scan_paths  # noqa: E402


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
        format_completed_axis_report(
            "R_native_crashes", r_native_crashes(offenders)
        ),
        (
            "Replacement: corpus children terminate with completed testimony, "
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


def _from_terminal(row: FileTerminal) -> ChildResult:
    if row.category == "native-crash":
        rc = row.returncode if row.returncode is not None else -1
        offender = native_crash_offender(
            file=row.file, returncode=rc, stderr=row.stderr_tail
        )
        if offender is None and row.signal_name:
            offender = NativeCrashOffender(
                row.file, rc, row.signal_name, row.stderr_tail
            )
        return ChildResult(row.file, "native-crash", rc, row.stderr_tail, offender)
    if row.category in {"bare-exception"}:
        return ChildResult(
            row.file, "non-native-red", row.returncode, row.stderr_tail, None
        )
    return ChildResult(row.file, row.category, row.returncode, row.stderr_tail, None)


def audit_paths(
    paths: Sequence[Path],
    *,
    root: Path,
    file_timeout: int,
    progress_path: Path | None = None,
) -> AuditSummary:
    """Measure every path. Durable reuse is the content-addressed process-floor
    terminal cache (tip × corpus × axis × file-content cid), not a side
    checkpoint journal.
    """
    if file_timeout > 30:
        raise ValueError("per-file timeout may not exceed 30 seconds")
    terminals = scan_paths(paths, root=root, file_timeout=float(file_timeout))
    if progress_path is not None:
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        with progress_path.open("w", encoding="utf-8") as stream:
            stream.write(f"# native-crash supervised enum scan files={len(paths)}\n")
            for t in terminals:
                stream.write(f"{t.file}\t{t.category}\n")
    rows = tuple(_from_terminal(t) for t in terminals)
    offenders = tuple(row.offender for row in rows if row.offender is not None)
    return AuditSummary(
        discovered=len(rows),
        completed=sum(row.category in {"completed", "typed-gap"} for row in rows),
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
        default=[],
        help=(
            "Scan roots (required, non-empty). Process floors police the "
            "authenticated pandas corpus — never silent kit production_roots."
        ),
    )
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    parser.add_argument("--file-timeout", type=int, default=30)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--engine-log", type=Path, default=None)
    parser.add_argument("--progress", type=Path, default=None)
    args = parser.parse_args()

    boot_error = production_lift_bootstrap_error()
    if boot_error is not None:
        print(
            "NATIVE-CRASH SCANNER INFRASTRUCTURE FAILURE: the production "
            f"lift door did not bootstrap: {boot_error}"
        )
        return 2

    try:
        paths = require_explicit_scan_roots(args.paths)
    except ValueError as error:
        print(f"NATIVE-CRASH ZERO-TOLERANCE RED: {error}")
        return 1
    print(
        "NATIVE-CRASH POPULATION: "
        f"roots={[str(p) for p in args.paths]} files={len(paths)}"
    )

    try:
        _base, engine_path, progress_path = prepare_floor_io(
            repo_root=args.repo_root,
            floor="native-crash",
            out_dir=args.out_dir,
            engine_log=args.engine_log,
            progress=args.progress,
        )
    except (OSError, ValueError) as error:
        print(format_unmeasured_axis("R_native_crashes", reason=str(error)))
        return 1
    summary = audit_paths(
        paths,
        root=args.repo_root,
        file_timeout=args.file_timeout,
        progress_path=progress_path,
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
