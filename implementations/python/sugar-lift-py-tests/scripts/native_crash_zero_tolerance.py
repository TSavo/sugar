#!/usr/bin/env python3
"""R_native_crashes — permanent baseline-free corpus process floor.

Each source file runs in an isolated Python child with faulthandler enabled.
Only signal termination is a native crash. ConstructionPanic, ordinary exceptions,
and timeouts stay loud in their own categories and are never softened into
success or folded into this axis.

Exit 1 whenever R_native_crashes > 0; there is no baseline or allowlist.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import signal
import subprocess
import sys

# Floors share ``_production_lift_child`` (this directory); make it
# importable whether run standalone, as a child, or spec-loaded by a test.
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parent))
from typing import NamedTuple, Sequence


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
            "Replacement: corpus children terminate with completed testimony, "
            "typed ConstructionPanic, bare-exception row, or loud timeout; never signal."
        ),
        "",
        "Loci:",
    ]
    for row in offenders:
        lines.append(f"{row.file}:returncode={row.returncode}:signal={row.signal}")
        if row.stderr_tail:
            lines.append(row.stderr_tail)
    return "\n".join(lines)


def _python_paths(roots: Sequence[Path]) -> list[Path]:
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
    paths = _python_paths(roots)
    if not paths:
        raise ValueError(f"no Python source files found under {list(roots)}")
    return paths


def _run_isolated(
    path: Path,
    *,
    root: Path,
    file_timeout: int,
) -> ChildResult:
    script = Path(__file__).resolve()
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    env = dict(os.environ)
    env["PYTHONFAULTHANDLER"] = "1"
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--child-file",
                str(path),
                "--child-rel",
                rel,
            ],
            text=True,
            capture_output=True,
            timeout=file_timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return ChildResult(
            rel,
            "timeout",
            None,
            (error.stderr or "")[-2000:] if isinstance(error.stderr, str) else "",
            None,
        )
    offender = native_crash_offender(
        file=rel,
        returncode=result.returncode,
        stderr=result.stderr,
    )
    if offender is not None:
        return ChildResult(
            rel, "native-crash", result.returncode, result.stderr[-2000:], offender
        )
    if result.returncode:
        return ChildResult(
            rel, "non-native-red", result.returncode, result.stderr[-2000:], None
        )
    return ChildResult(rel, "completed", result.returncode, "", None)


def audit_paths(
    paths: Sequence[Path],
    *,
    root: Path,
    file_timeout: int,
    workers: int,
) -> AuditSummary:
    with ThreadPoolExecutor(max_workers=workers) as executor:
        rows = list(
            executor.map(
                lambda path: _run_isolated(
                    path,
                    root=root,
                    file_timeout=file_timeout,
                ),
                sorted(paths),
            )
        )
    offenders = tuple(row.offender for row in rows if row.offender is not None)
    for row in rows:
        if row.category == "timeout":
            print(
                f"LOUD timeout row: {row.file}: exceeded {file_timeout}s",
                flush=True,
            )
        elif row.category == "non-native-red":
            tail = (row.stderr_tail.splitlines() or ["no stderr"])[-1]
            print(
                f"LOUD non-native red row: {row.file}: "
                f"returncode={row.returncode}: {tail}",
                flush=True,
            )
    return AuditSummary(
        discovered=len(rows),
        completed=sum(row.category == "completed" for row in rows),
        timeouts=sum(row.category == "timeout" for row in rows),
        non_native_red=sum(row.category == "non-native-red" for row in rows),
        offenders=offenders,
        rows=tuple(rows),
    )


def _run_child(path: Path, rel: str) -> int:
    from _production_lift_child import run_production_lift_child

    return run_production_lift_child(path, rel)


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
    parser.add_argument(
        "--workers",
        type=int,
        default=min(16, max(1, os.cpu_count() or 1)),
    )
    parser.add_argument("--child-file", type=Path)
    parser.add_argument("--child-rel")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    if args.child_file or args.child_rel:
        if args.child_file is None or args.child_rel is None:
            parser.error("child mode requires --child-file and --child-rel")
        return _run_child(args.child_file, args.child_rel)
    from _production_lift_child import production_lift_bootstrap_error

    boot_error = production_lift_bootstrap_error()
    if boot_error is not None:
        # ONE infrastructure failure -- never multiplied per source file.
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
    summary = audit_paths(
        paths,
        root=args.repo_root,
        file_timeout=args.file_timeout,
        workers=max(1, args.workers),
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
                "nonNativeRed": summary.non_native_red,
                "timeouts": summary.timeouts,
            },
            measured=summary.timeouts == 0,
            unmeasurable_reasons=("timeout",) if summary.timeouts else (),
        )
        write_json(args.json, payload)
    print(
        "NATIVE-CRASH SURFACE: "
        f"discovered={summary.discovered} completed={summary.completed} "
        f"non_native_red={summary.non_native_red} timeouts={summary.timeouts}"
    )
    if summary.offenders:
        print("NATIVE-CRASH ZERO-TOLERANCE RED")
        print(format_report(summary.offenders))
        return 1
    print("NATIVE-CRASH ZERO-TOLERANCE GREEN: R_native_crashes = 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
