#!/usr/bin/env python3
"""R_timeouts — permanent baseline-free bounded-termination floor.

Classifier over the supervised :class:`FileTerminal` stream (category
``timeout``). Full corpus CI uses ``process_floor_shared_pass.py`` (one lift,
three projections). This CLI stays for discrimination / solo runs.
"""

from __future__ import annotations

# Not the board. This module measures its own named denominator; the sole
# authoritative Python corpus scoreboard is scripts/control_effect_recensus.py.
# See tests/test_one_authoritative_scoreboard.py.
SCOREBOARD_AUTHORITY = False

import argparse
from pathlib import Path
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
from _process_floor_shared_pass import (  # noqa: E402
    TimeoutOffender,
    project_timeout,
    shared_process_floor_pass,
)
from _production_lift_child import production_lift_bootstrap_error  # noqa: E402
from _supervised_enum_supervisor import FileTerminal  # noqa: E402


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
    return ChildResult(
        row.file, row.category, project_timeout(row, file_timeout=file_timeout)
    )


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
    """Project timeout residuals from the **shared** supervised pass."""
    del workers, checkpoint_path, progress_stdout
    shared = shared_process_floor_pass(
        paths, root=root, file_timeout=float(file_timeout)
    )
    if progress_path is not None:
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        with progress_path.open("w", encoding="utf-8") as stream:
            stream.write(f"# timeout projection (shared pass) files={len(paths)}\n")
            for t in shared.terminals:
                stream.write(f"{t.file}\t{t.category}\n")
    rows = tuple(
        _from_terminal(t, file_timeout=float(file_timeout)) for t in shared.terminals
    )
    return AuditSummary(rows=rows, offenders=shared.timeouts)


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
        paths = require_explicit_scan_roots(args.paths)
    except ValueError as error:
        print(f"TIMEOUT ZERO-TOLERANCE RED: {error}")
        return 1
    print(
        "TIMEOUT POPULATION: "
        f"roots={[str(p) for p in args.paths]} files={len(paths)}"
    )

    try:
        _base, engine_path, progress_path = prepare_floor_io(
            repo_root=args.repo_root,
            floor="timeout",
            out_dir=args.out_dir,
            engine_log=args.engine_log,
            progress=args.progress,
        )
    except (OSError, ValueError) as error:
        print(format_unmeasured_axis("R_timeouts", reason=str(error)))
        return 1
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
                "bareExceptions": sum(row.category == "bare-exception" for row in rows),
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
    print(format_completed_axis_report("R_timeouts", len(offenders)))
    for row in offenders:
        print(f"{row.file}:timeout>{row.timeout_seconds}s")
    return 1 if offenders else 0


if __name__ == "__main__":
    raise SystemExit(main())
