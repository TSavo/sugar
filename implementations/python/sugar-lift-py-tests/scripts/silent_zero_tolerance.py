#!/usr/bin/env python3
"""R_silent — Criterion 2 fourth term: silent/unaccounted construction loci.

## Class

**Silent/unaccounted** = a source locus that is on disk (assert or body) and
is absent from the construction roll call as either *warranted* or
*unresolved*. The locus vanished from the denominator without classification.

That is Crime-1 construction completeness (lift_coverage_accounting doctrine):
stated work that never engaged the instrument. Panic / gap / timeout /
native-crash are *classified* failures — not silent.

## Population law (Criterion 2)

Criterion 2 requires, over the **authenticated pandas corpus**,
simultaneously:

    R(construction panics) = R(native crashes) = R(timeouts) = R(silent) = 0

Native / timeout / bare-exception floors already refuse empty scan roots and
are bound to ``PANDAS_CORPUS`` in ``tools/run_sole_construction_floors.sh``.
This floor must do the same: **explicit non-empty scan roots required**.
Defaulting to kit ``production_roots`` (~444 files) is a wrong-population
false green — R=0 on kit while the corpus is never entered.

## Not this class (do not collapse)

| Axis | Owner | Difference |
| --- | --- | --- |
| ``Unmeasured`` / SHELF_UNMEASURED | commit_measurement / shelf | Measurement *of* measurement: no reading was taken |
| Heavy attendance absent-artifact | heavy_measurement_attendance | Job never ran / no artifact |
| Gap / ConstructionPanic held | roll call ``unresolved`` | Instrument engaged; unfinished is classified |
| R_silent | **this module** | Disk locus never appeared on the roll call |

## Predicate

    silent ⇔ (file, line, col, kind) ∈ disk_census
             ∧ (file, line, col, kind) ∉ roll_call{warranted ∪ unresolved}

## Ladder

Auditor over (disk census × roll call). Type cannot close open source
populations. Retirement: every disk locus is constructed into the roll call
or classified; then silence at stable zero on the **corpus** population.

## Performance (membership only)

Silent keys on **membership** of disk loci in ``warranted ∪ unresolved``.
Both statuses are roster members; sugar **discharge** only splits Blue/Yellow
and does not change membership for nodes registered at tree materialize.

Production path therefore uses **register-only** roster construction
(``source_audit_membership_from_registration``), not full ``discharge`` /
per-root ``sugar()``. Discharge remains available for the identity twin and
for report feeds that need present-vs-minority.

Empty disk census (no asserts, no function bodies) contributes 0 by predicate
construction — skip tree construction entirely for those files.

In-process enum scan. Progress and engine logs never mix.
"""

from __future__ import annotations

# Not the board. This module measures its own named denominator; the sole
# authoritative Python corpus scoreboard is scripts/control_effect_recensus.py.
# See tests/test_one_authoritative_scoreboard.py.
SCOREBOARD_AUTHORITY = False

import argparse
from pathlib import Path
import sys
from typing import Any, Mapping, NamedTuple, Sequence  # Any used in audit_paths

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sugar_lift_py_tests.idd.lift_coverage_census import DiskCensus  # noqa: E402

from _enum_floor_runtime import (  # noqa: E402
    format_completed_axis_report,
    format_unmeasured_axis,
    iter_with_tqdm,
    open_progress,
    prepare_floor_io,
    production_roots,
    relative_to_root,
    require_explicit_scan_roots,
    require_python_paths,
    with_file_timeout,
    add_lpt_shard_args,
    apply_lpt_file_shard,
)


class SilentOffender(NamedTuple):
    file: str
    kind: str
    count: int
    note: str


class ChildResult(NamedTuple):
    file: str
    category: str
    offenders: tuple[SilentOffender, ...]
    returncode: int | None
    stderr_tail: str


class AuditSummary(NamedTuple):
    discovered: int
    completed: int
    construction_panics: int
    timeouts: int
    non_native_red: int
    native_crashes: int
    offenders: tuple[SilentOffender, ...]
    rows: tuple[ChildResult, ...]


def _roll_call_keys(audit: Mapping[str, Any]) -> set[tuple[str, int, int, str]]:
    keys = set()
    for raw in audit.get("loci", []):
        if not isinstance(raw, Mapping):
            continue
        status = raw.get("status")
        locus = raw.get("locus")
        kind = raw.get("kind")
        if status not in {"warranted", "unresolved"} or not isinstance(locus, Mapping):
            continue
        file = locus.get("file")
        line = locus.get("line")
        col = locus.get("col")
        if (
            isinstance(file, str)
            and isinstance(line, int)
            and isinstance(col, int)
            and isinstance(kind, str)
        ):
            keys.add((file, line, col, kind))
    return keys


def silent_offenders(
    census: DiskCensus, audit: Mapping[str, Any]
) -> list[SilentOffender]:
    """Return disk loci absent from the construction roll-call roster."""
    constructed_or_gap = _roll_call_keys(audit)
    disk_loci = [
        (locus.file, locus.line, locus.col, "Assert") for locus in census.asserts
    ] + [(locus.file, locus.line, locus.col, locus.kind) for locus in census.bodies]
    return [
        SilentOffender(
            file=f"{file}:{line}:{col}",
            kind=f"silent-{kind}",
            count=1,
            note="on-disk source locus is absent from the construction roll call",
        )
        for file, line, col, kind in disk_loci
        if (file, line, col, kind) not in constructed_or_gap
    ]


def disk_census_empty(census: DiskCensus) -> bool:
    """No asserts and no function bodies → R_silent contribution is 0 by predicate."""
    return not census.asserts and not census.bodies


def r_silent(offenders: Sequence[SilentOffender]) -> int:
    return sum(row.count for row in offenders)


def format_report(offenders: Sequence[SilentOffender]) -> str:
    lines = [
        format_completed_axis_report("R_silent", r_silent(offenders)),
        (
            "Replacement: every source locus speaks as warranted, support, "
            "inactive, typed effect, or loud ConstructionPanic."
        ),
        "",
        "Loci:",
    ]
    for row in offenders:
        lines.append(f"{row.file}:{row.kind}:count={row.count} — {row.note}")
    return "\n".join(lines)


def _audit_file_discharge(
    path: Path, *, rel: str
) -> tuple[str, tuple[SilentOffender, ...]]:
    """Reference path: full register + sugar discharge (identity twin only)."""
    from sugar_lift_py_tests.idd.lift_coverage_census import census_source
    from sugar_lift_py_tests.tree_enumerate import source_audit_from_roll_call

    source = path.read_text(encoding="utf-8", errors="replace")
    census = census_source(source, file=rel)
    if disk_census_empty(census):
        return "completed", ()
    audit = source_audit_from_roll_call(path, rel)
    return "completed", tuple(silent_offenders(census, audit))


def _audit_file(path: Path, *, rel: str) -> tuple[str, tuple[SilentOffender, ...]]:
    """Production path: disk census + register-only roster membership.

    Does not call ``sugar()`` / discharge. Membership of disk loci in the
    roll-call key set is identical to the discharge path (see twin tests).
    """
    from sugar_lift_py_tests.idd.lift_coverage_census import census_source
    from sugar_lift_py_tests.tree_enumerate import (
        source_audit_membership_from_registration,
    )

    source = path.read_text(encoding="utf-8", errors="replace")
    census = census_source(source, file=rel)
    # Empty disk census → 0 silent by construction; skip tree work entirely.
    if disk_census_empty(census):
        return "completed", ()
    audit = source_audit_membership_from_registration(path, rel)
    return "completed", tuple(silent_offenders(census, audit))


def _run_one(path: Path, *, root: Path, file_timeout: int) -> ChildResult:
    rel = relative_to_root(path, root)
    try:

        def _work() -> tuple[str, tuple[SilentOffender, ...]]:
            return _audit_file(path, rel=rel)

        category, offenders = with_file_timeout(file_timeout, _work)
        return ChildResult(rel, category, offenders, 0, "")
    except TimeoutError as error:
        return ChildResult(rel, "timeout", (), None, str(error))
    # ConstructionPanic is BaseException — must not be held here. Let it kill
    # the process; supervised floors attribute the in-flight file loudly.
    except Exception as error:
        return ChildResult(
            rel,
            "non-native-red",
            (),
            1,
            f"{type(error).__name__}: {error}"[-2000:],
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
        checkpoint = Checkpoint(floor="silent", files=files, path=checkpoint_path)
        for row in checkpoint.rows():
            raw = row["result"]
            file = str(row["file"])
            offenders = tuple(
                SilentOffender(
                    file=str(offender["file"]),
                    kind=str(offender["kind"]),
                    count=int(offender["count"]),
                    note=str(offender["note"]),
                )
                for offender in raw.get("offenders", [])
                if isinstance(offender, Mapping)
            )
            returncode = raw.get("returncode")
            done_rows[file] = ChildResult(
                file,
                str(raw.get("category")),
                offenders,
                int(returncode) if isinstance(returncode, int) else None,
                str(raw.get("stderrTail") or ""),
            )
        pending = [by_rel[r] for r in checkpoint.pending_files()]

    progress_stream = None
    if progress_path is not None:
        progress_stream = open_progress(
            progress_path,
            header=(
                f"# silent floor (in-process enum)\n"
                f"# files={len(paths)} pending={len(pending)}\n"
            ),
        )
    files_total = len(paths)
    pending_total = len(pending)
    already_done = files_total - pending_total
    from job_log_heartbeat import JobLogHeartbeat

    beat = JobLogHeartbeat("silent-audit", total=files_total)
    beat.n = already_done
    beat.watch()
    beat.tick(
        n=already_done,
        force=True,
        status="denominator",
        pending=pending_total,
        file_timeout_s=file_timeout,
    )
    try:
        iterator: Any = pending
        if progress_stream is not None:
            iterator = iter_with_tqdm(
                pending,
                progress=progress_stream,
                total=files_total,
                initial=already_done,
                desc="silent",
                # Always mirror when requested — never isatty-gate job log.
                progress_stdout=True if progress_stdout else False,
            )
        for file_i, path in enumerate(pending, start=1):
            rel = relative_to_root(path, root)
            beat.tick(
                n=already_done + file_i - 1,
                force=True,
                status="audit-file",
                file=rel,
                pending_index=file_i,
                pending_total=pending_total,
            )
            row = _run_one(path, root=root, file_timeout=file_timeout)
            if checkpoint is not None:
                checkpoint.append(
                    row.file,
                    {
                        "category": row.category,
                        "offenders": [o._asdict() for o in row.offenders],
                        "returncode": row.returncode,
                        "stderrTail": row.stderr_tail,
                    },
                )
            done_rows[row.file] = row
            beat.tick(
                n=already_done + file_i,
                force=(file_i == pending_total or file_i % 10 == 0),
                status="file-done",
                file=row.file,
                category=row.category,
                silent_loci=r_silent(row.offenders),
            )
    finally:
        beat.stop(status="audit-complete")
        if progress_stream is not None:
            progress_stream.close()

    if checkpoint is not None:
        rows = tuple(
            done_rows[f] if f in done_rows else ChildResult(f, "missing", (), None, "")
            for f in checkpoint.files
        )
    else:
        rows = tuple(done_rows[relative_to_root(p, root)] for p in sorted(paths))
    offenders = tuple(o for row in rows for o in row.offenders)
    return AuditSummary(
        discovered=len(rows),
        completed=sum(row.category == "completed" for row in rows),
        construction_panics=sum(row.category == "factory-panic" for row in rows),
        timeouts=sum(row.category == "timeout" for row in rows),
        non_native_red=sum(row.category == "non-native-red" for row in rows),
        native_crashes=sum(row.category == "native-crash" for row in rows),
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
            "Scan roots (required, non-empty). Criterion-2 silent floor police "
            "the authenticated pandas corpus — never silent kit production_roots."
        ),
    )
    parser.add_argument("--live-root", action="append", type=Path, default=[])
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    parser.add_argument("--file-timeout", type=int, default=30)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--checkpoint-jsonl", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--engine-log", type=Path, default=None)
    parser.add_argument("--progress", type=Path, default=None)
    add_lpt_shard_args(parser)
    parser.add_argument("--progress-stdout", action="store_true")
    args = parser.parse_args()

    try:
        # Same population door as native_crash / timeout / bare_exception:
        # refuse empty args. Kit production_roots is never an implied default.
        roots = list(args.live_root) + list(args.paths)
        paths = require_explicit_scan_roots(roots)
        paths = apply_lpt_file_shard(
            paths,
            root=args.repo_root,
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            population="process-floor-silent",
        )
    except ValueError as error:
        print(f"SILENT ZERO-TOLERANCE RED: {error}")
        return 2

    try:
        _base, engine_path, progress_path = prepare_floor_io(
            repo_root=args.repo_root,
            floor="silent",
            out_dir=args.out_dir,
            engine_log=args.engine_log,
            progress=args.progress,
        )
    except (OSError, ValueError) as error:
        print(format_unmeasured_axis("R_silent", reason=str(error)))
        return 2
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
        from pandas_floor_summary import (
            relative_files,
            write_floor_summary_or_unmeasured,
        )

        files = relative_files(paths, args.repo_root)
        residual_count = r_silent(summary.offenders)
        write_floor_summary_or_unmeasured(
            args.json,
            floor="silent",
            residual_key="R_silent",
            residual_count=residual_count,
            files=files,
            rows=[
                {
                    "file": row.file,
                    "category": row.category,
                    "silentLoci": [offender._asdict() for offender in row.offenders],
                    "silentCount": r_silent(row.offenders),
                }
                for row in summary.rows
            ],
            totals={
                "R_silent": residual_count,
                "completed": summary.completed,
                "constructionPanics": summary.construction_panics,
                "nativeCrashes": summary.native_crashes,
                "nonNativeRed": summary.non_native_red,
                "timeouts": summary.timeouts,
            },
            measured=len(summary.rows) == len(files),
            unmeasurable_reasons=(),
        )
    print(
        "SILENT SURFACE: "
        f"files_discovered={summary.discovered} files_completed={summary.completed} "
        f"construction_panics={summary.construction_panics} "
        f"non_native_red={summary.non_native_red} "
        f"timeouts={summary.timeouts} "
        f"progress={progress_path} engine={engine_path}"
    )
    print(format_report(summary.offenders))
    return 1 if r_silent(summary.offenders) else 0


if __name__ == "__main__":
    raise SystemExit(main())
