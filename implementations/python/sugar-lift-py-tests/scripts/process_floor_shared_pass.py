#!/usr/bin/env python3
"""CI door: one supervised pass → R_native_crashes + R_bare_exceptions + R_timeouts.

Replaces three sequential zero-tolerance corpus lifts in
``tools/run_sole_construction_floors.sh``. Discrimination unit tests and the
legacy per-axis CLIs remain; the **binding** floor set uses this door so the
corpus is lifted once.

Exit 1 if any of the three R axes is non-zero. Exit 2 on infrastructure
failure. Coverage breach (fewer terminals than paths) is infrastructure red.
"""

from __future__ import annotations

SCOREBOARD_AUTHORITY = False

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _enum_floor_runtime import (  # noqa: E402
    format_completed_axis_report,
    format_unmeasured_axis,
    prepare_floor_io,
    require_explicit_scan_roots,
)
from _process_floor_shared_pass import shared_process_floor_pass  # noqa: E402
from _production_lift_child import production_lift_bootstrap_error  # noqa: E402


def main(argv: list[str] | None = None) -> int:
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
            "Scan roots (required, non-empty). Authenticated pandas corpus — "
            "never silent kit production_roots."
        ),
    )
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    parser.add_argument("--file-timeout", type=int, default=30)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--engine-log", type=Path, default=None)
    parser.add_argument("--progress", type=Path, default=None)
    args = parser.parse_args(argv)

    boot_error = production_lift_bootstrap_error()
    if boot_error is not None:
        print(
            "PROCESS-FLOOR SHARED PASS INFRASTRUCTURE FAILURE: the production "
            f"lift door did not bootstrap: {boot_error}"
        )
        return 2

    try:
        paths = require_explicit_scan_roots(args.paths)
    except ValueError as error:
        print(f"PROCESS-FLOOR SHARED PASS RED: {error}")
        return 1

    print(
        "PROCESS-FLOOR SHARED POPULATION: "
        f"roots={[str(p) for p in args.paths]} files={len(paths)} "
        f"(one supervised pass → three projections)"
    )

    try:
        _base, engine_path, progress_path = prepare_floor_io(
            repo_root=args.repo_root,
            floor="process-shared",
            out_dir=args.out_dir,
            engine_log=args.engine_log,
            progress=args.progress,
        )
    except (OSError, ValueError) as error:
        print(format_unmeasured_axis("R_native_crashes", reason=str(error)))
        print(format_unmeasured_axis("R_bare_exceptions", reason=str(error)))
        print(format_unmeasured_axis("R_timeouts", reason=str(error)))
        return 1

    try:
        result = shared_process_floor_pass(
            paths,
            root=args.repo_root,
            file_timeout=float(args.file_timeout),
        )
    except RuntimeError as error:
        print(f"PROCESS-FLOOR SHARED PASS INFRASTRUCTURE FAILURE: {error}")
        return 2

    progress_path.parent.mkdir(parents=True, exist_ok=True)
    with progress_path.open("w", encoding="utf-8") as stream:
        stream.write(
            f"# process-floor shared pass files={len(paths)} "
            f"terminals={result.discovered}\n"
        )
        for t in result.terminals:
            stream.write(f"{t.file}\t{t.category}\trestarts={t.worker_restarts}\n")

    print(
        "PROCESS-FLOOR SHARED SURFACE: "
        f"discovered={result.discovered} "
        f"native={result.r_native_crashes()} "
        f"bare={result.r_bare_exceptions()} "
        f"timeouts={result.r_timeouts()} "
        f"progress={progress_path} engine={engine_path}"
    )
    # Three completed axes from one stream — never a merged single R.
    print(format_completed_axis_report("R_native_crashes", result.r_native_crashes()))
    for row in result.native_crashes:
        print(f"{row.file}:returncode={row.returncode}:signal={row.signal}")
        if row.stderr_tail:
            print(row.stderr_tail)
    print(
        format_completed_axis_report("R_bare_exceptions", result.r_bare_exceptions())
    )
    for row in result.bare_exceptions:
        tail = (row.stderr_tail.splitlines() or ["no detail"])[-1]
        print(f"{row.file}:returncode={row.returncode}:bare-exception — {tail}")
    print(format_completed_axis_report("R_timeouts", result.r_timeouts()))
    for row in result.timeouts:
        print(f"{row.file}:timeout>{row.timeout_seconds}s")

    return 1 if result.any_red() else 0


if __name__ == "__main__":
    raise SystemExit(main())
