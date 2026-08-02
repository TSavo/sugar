#!/usr/bin/env python3
"""R_bare_exceptions — permanent baseline-free untyped-failure floor.

Supervised persistent enum worker: reuses process across healthy files;
restarts on native crash / timeout. Enumeration protocol only.
"""

from __future__ import annotations

# Not the board. This module measures its own named denominator; the sole
# authoritative Python corpus scoreboard is scripts/control_effect_recensus.py.
# See tests/test_one_authoritative_scoreboard.py.
SCOREBOARD_AUTHORITY = False

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, NamedTuple, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _enum_floor_runtime import (  # noqa: E402
    format_completed_axis_report,
    format_unmeasured_axis,
    prepare_floor_io,
    production_roots,
    require_explicit_scan_roots,
    require_python_paths,
    add_lpt_shard_args,
    apply_lpt_file_shard,
)
from _production_lift_child import (  # noqa: E402
    NON_FAILURE_OUTCOMES,
    OUTCOME_COMPLETED,
    OUTCOME_TYPED_GAP,
    production_lift_bootstrap_error,
)
from _supervised_enum_supervisor import FileTerminal, scan_paths  # noqa: E402


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


def _from_terminal(row: FileTerminal) -> ChildResult:
    if row.category == "bare-exception":
        return ChildResult(
            row.file,
            "bare-exception",
            BareExceptionOffender(
                row.file,
                row.returncode if row.returncode is not None else 1,
                row.stderr_tail,
            ),
        )
    return ChildResult(row.file, row.category, None)


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
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--engine-log", type=Path, default=None)
    parser.add_argument("--progress", type=Path, default=None)
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write pandas-floor-summary-v1 with R_bare_exceptions magnitude.",
    )
    add_lpt_shard_args(parser)
    args = parser.parse_args()

    boot_error = production_lift_bootstrap_error()
    if boot_error is not None:
        print(
            "BARE-EXCEPTION SCANNER INFRASTRUCTURE FAILURE: the production lift "
            f"door did not bootstrap: {boot_error}"
        )
        return 2
    try:
        paths = require_explicit_scan_roots(args.paths)
        paths = apply_lpt_file_shard(
            paths,
            root=args.repo_root,
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            population="process-floor-bare-exception",
        )
    except ValueError as error:
        print(f"BARE-EXCEPTION ZERO-TOLERANCE RED: {error}")
        return 2
    print(
        "BARE-EXCEPTION POPULATION: "
        f"roots={[str(p) for p in args.paths]} files={len(paths)}"
    )

    try:
        _base, engine_path, progress_path = prepare_floor_io(
            repo_root=args.repo_root,
            floor="bare-exception",
            out_dir=args.out_dir,
            engine_log=args.engine_log,
            progress=args.progress,
        )
    except (OSError, ValueError) as error:
        print(format_unmeasured_axis("R_bare_exceptions", reason=str(error)))
        return 2
    progress_path.write_text(
        f"# bare-exception supervised enum scan\n"
        f"# engine={engine_path}\n"
        f"# files={len(paths)}\n",
        encoding="utf-8",
    )
    terminals = scan_paths(
        paths, root=args.repo_root, file_timeout=float(args.file_timeout)
    )
    rows = tuple(_from_terminal(t) for t in terminals)
    with progress_path.open("a", encoding="utf-8") as progress:
        for t in terminals:
            progress.write(f"{t.file}\t{t.category}\trestarts={t.worker_restarts}\n")

    offenders = tuple(row.offender for row in rows if row.offender is not None)
    if args.json is not None:
        from pandas_floor_summary import (
            relative_files,
            write_floor_summary_or_unmeasured,
        )

        files = relative_files(paths, args.repo_root)
        residual_count = len(offenders)
        write_floor_summary_or_unmeasured(
            args.json,
            floor="bare-exception",
            residual_key="R_bare_exceptions",
            residual_count=residual_count,
            files=files,
            rows=[
                {
                    "file": row.file,
                    "category": row.category,
                    "returncode": None,
                }
                for row in rows
            ],
            totals={
                "R_bare_exceptions": residual_count,
                "completed": sum(
                    row.category == OUTCOME_COMPLETED for row in rows
                ),
                "typedGaps": sum(
                    row.category == OUTCOME_TYPED_GAP for row in rows
                ),
                "timeouts": sum(row.category == "timeout" for row in rows),
                "nativeCrashes": sum(
                    row.category == "native-crash" for row in rows
                ),
            },
            measured=True,
        )
    print(
        "BARE-EXCEPTION SURFACE: "
        f"discovered={len(rows)} "
        f"completed={sum(row.category == OUTCOME_COMPLETED for row in rows)} "
        f"typed_gaps={sum(row.category == OUTCOME_TYPED_GAP for row in rows)} "
        f"timeouts={sum(row.category == 'timeout' for row in rows)} "
        f"native_crashes={sum(row.category == 'native-crash' for row in rows)} "
        f"bare={len(offenders)} "
        f"progress={progress_path} engine={engine_path}"
    )
    print(format_completed_axis_report("R_bare_exceptions", len(offenders)))
    for row in offenders:
        tail = (row.stderr_tail.splitlines() or ["no detail"])[-1]
        print(f"{row.file}:returncode={row.returncode}:bare-exception — {tail}")
    return 1 if offenders else 0


if __name__ == "__main__":
    raise SystemExit(main())
