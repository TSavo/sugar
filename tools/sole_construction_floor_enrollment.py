#!/usr/bin/env python3
"""Sole-construction floor enrollment — completeness by roll call, not sum of R.

T: serializing floors on a multi-runner fleet is pure insanity. Process axes
run as a matrix; wall clock is max(job), not sum. Completeness is enrollment:
a missing seat is UNMEASURED, never a smaller green set.

Process population is file-sharded with LPT (k=8) on a measured cost prior —
same key as the suite. Each (axis × file-shard) is an enrolled seat:
  silent-s00..s07 | native-crash-s00.. | bare-exception-s00.. | timeout-s00..

Static laws (cheap AST / discrimination): one parallel job that does not wait
on the process matrix.

Each job writes an identity-bound floor-axis-report.json. Attendance checks
the enrolled roster; residual red is the seat job's own exit code.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

SCOREBOARD_AUTHORITY = False

REPORT_KIND = "sole-construction-floor-axis-report"
REPORT_FILENAME = "floor-axis-report.json"
CAMPAIGN_CLASS = "python-sole-construction-floors"
CAMPAIGN_BODY = "floor-measurement.json"

# File-shard k — keep with suite. Split key is LPT, not raising k.
PROCESS_FILE_SHARD_COUNT = 8


@dataclass(frozen=True, slots=True)
class FloorAxis:
    axis_id: str
    display: str
    kind: str  # process | static
    script: str | None = None  # process floors only


PROCESS_AXIS_BASE: tuple[FloorAxis, ...] = (
    FloorAxis("silent", "R_silent", "process", "silent_zero_tolerance.py"),
    FloorAxis(
        "native-crash", "R_native_crashes", "process", "native_crash_zero_tolerance.py"
    ),
    FloorAxis(
        "bare-exception",
        "R_bare_exceptions",
        "process",
        "bare_exception_zero_tolerance.py",
    ),
    FloorAxis("timeout", "R_timeouts", "process", "timeout_zero_tolerance.py"),
)

# Back-compat alias: base axes without file-shard seats.
PROCESS_AXES = PROCESS_AXIS_BASE


def process_shard_seats(
    shard_count: int = PROCESS_FILE_SHARD_COUNT,
) -> tuple[FloorAxis, ...]:
    seats: list[FloorAxis] = []
    for axis in PROCESS_AXIS_BASE:
        for shard in range(shard_count):
            seats.append(
                FloorAxis(
                    f"{axis.axis_id}-s{shard:02d}",
                    f"{axis.display}[s{shard:02d}]",
                    "process",
                    axis.script,
                )
            )
    return tuple(seats)


# One enrollment slot for the cheap static job (ownership, side doors, …).
STATIC_AXIS = FloorAxis("static-laws", "R_static_sole_construction", "static")

ENROLLED: tuple[FloorAxis, ...] = process_shard_seats() + (STATIC_AXIS,)


def enrolled_ids() -> tuple[str, ...]:
    return tuple(a.axis_id for a in ENROLLED)


def emit_process_matrix_json(
    shard_count: int = PROCESS_FILE_SHARD_COUNT,
) -> str:
    """GitHub Actions matrix include: base axis × LPT file shard."""
    include = []
    for axis in PROCESS_AXIS_BASE:
        for shard in range(shard_count):
            include.append(
                {
                    "axis": axis.axis_id,
                    "axisSeat": f"{axis.axis_id}-s{shard:02d}",
                    "display": f"{axis.display}[s{shard:02d}]",
                    "script": axis.script,
                    "shard": shard,
                    "shardCount": shard_count,
                }
            )
    return json.dumps({"include": include})


# Exit-code vocabulary for enrollment mint (scan-complete vs infrastructure):
#   0 — scan completed; residual green (R=0)
#   1 — scan completed; residual red (R>0)
#   2+ — scan did NOT complete (auth/init/crash/IO); UNMEASURED, not residual
#
# Residual *magnitude* is never invented from exit code. Measured mints require
# residual_count cited from the floor's own summary under residual_key identity.
SCAN_COMPLETED_EXITS = frozenset({0, 1})

# Floor summary totals keys (pandas-floor-summary-v1) keyed by base axis id.
RESIDUAL_KEY_BY_BASE: dict[str, str] = {
    "silent": "R_silent",
    "native-crash": "R_native_crashes",
    "bare-exception": "R_bare_exceptions",
    "timeout": "R_timeouts",
    "static-laws": "R_static_sole_construction",
}


def base_axis_id(axis_id: str) -> str:
    """Map seat id (silent-s03) to base axis (silent)."""
    if axis_id == "static-laws":
        return axis_id
    # Seats: {base}-sNN
    if "-s" in axis_id:
        head, _, tail = axis_id.rpartition("-s")
        if len(tail) == 2 and tail.isdigit():
            return head
    return axis_id


def residual_key_for_axis(axis_id: str) -> str:
    base = base_axis_id(axis_id)
    key = RESIDUAL_KEY_BY_BASE.get(base)
    if key is None:
        raise ValueError(f"no residual key for axis_id {axis_id!r} (base={base!r})")
    return key


def load_residual_count_from_floor_summary(
    summary_path: Path, *, residual_key: str
) -> int:
    """Cite residual magnitude from a floor summary body — never invent.

    Accepts:
      - pandas-floor-summary-v1 with totals[residual_key]
      - floor-residual-v1 with residualKey + residualCount
    """
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"cannot read floor summary {summary_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"floor summary {summary_path} is not a JSON object")
    kind = payload.get("kind")
    if kind == "floor-residual-v1":
        if payload.get("residualKey") != residual_key:
            raise ValueError(
                f"floor-residual-v1 residualKey={payload.get('residualKey')!r} "
                f"!= expected {residual_key!r}"
            )
        raw = payload.get("residualCount")
        if type(raw) is not int or raw < 0:
            raise ValueError(
                f"floor-residual-v1 residualCount must be non-negative int; "
                f"got {type(raw).__name__}={raw!r}"
            )
        return raw
    totals = payload.get("totals")
    if not isinstance(totals, dict):
        raise ValueError(
            f"floor summary {summary_path} missing totals object "
            f"(need residual key {residual_key!r} under identity)"
        )
    if residual_key not in totals:
        raise ValueError(
            f"floor summary {summary_path} totals missing residual key "
            f"{residual_key!r}; present={sorted(totals)!r}"
        )
    raw = totals[residual_key]
    if type(raw) is not int or raw < 0:
        raise ValueError(
            f"floor summary residual {residual_key!r} must be a non-negative "
            f"int; got {type(raw).__name__}={raw!r}"
        )
    return raw


def mint_axis_report(
    *,
    axis_id: str,
    display: str,
    commit_sha: str,
    exit_code: int,
    kind: str,
    scan_completed: bool | None = None,
    unmeasured_reason: str | None = None,
    residual_count: int | None = None,
    residual_source: str | None = None,
    residual_key: str | None = None,
) -> dict:
    """Mint an identity-bound axis body.

    ``measured=True`` only when the scan completed (exit 0 or 1 by default)
    **and** residual_count is cited from the floor summary. Auth/init/crash
    (exit >= 2, or scan_completed=False) mints UNMEASURED with a named reason.

    Do **not** invent residual magnitude from exit code: exit 1 only says
    R>0; the count lives in the floor's own summary under residual_key.
    """
    if axis_id not in enrolled_ids():
        raise ValueError(f"axis_id {axis_id!r} is not enrolled")
    code = int(exit_code)
    if scan_completed is None:
        scan_completed = code in SCAN_COMPLETED_EXITS
    if scan_completed:
        if residual_count is None:
            raise ValueError(
                f"measured mint for {axis_id!r} requires residual_count from "
                f"the floor summary (do not invent R from exit code={code})"
            )
        if type(residual_count) is not int or residual_count < 0:
            raise ValueError(
                f"residual_count must be a non-negative int; got "
                f"{type(residual_count).__name__}={residual_count!r}"
            )
        rkey = residual_key or residual_key_for_axis(axis_id)
        return {
            "schemaVersion": 1,
            "kind": REPORT_KIND,
            "axisId": axis_id,
            "display": display,
            "axisKind": kind,
            "measurementClass": CAMPAIGN_CLASS,
            "measuredCommit": commit_sha,
            "status": "completed",
            "exitCode": code,
            "identityResolved": True,
            "measured": True,
            # Green iff residual count is zero — count is authoritative, not exit.
            "floorExitGreen": residual_count == 0,
            "unmeasuredReason": None,
            "residualCount": residual_count,
            "residualKey": rkey,
            "residualSource": residual_source or "floor-summary",
            # totals.failed carries magnitude for CommitMeasurement cite path.
            "totals": {
                "failed": residual_count,
                "residual": residual_count,
            },
        }
    reason = unmeasured_reason or (
        f"scan did not complete (exit={code}); infrastructure/auth/init/crash "
        "— not a residual reading"
    )
    return {
        "schemaVersion": 1,
        "kind": REPORT_KIND,
        "axisId": axis_id,
        "display": display,
        "axisKind": kind,
        "measurementClass": CAMPAIGN_CLASS,
        "measuredCommit": commit_sha,
        "status": "unmeasured",
        "exitCode": code,
        "identityResolved": True,
        "measured": False,
        "floorExitGreen": False,
        "unmeasuredReason": reason,
        "residualCount": None,
        "totals": {"failed": 1, "unmeasured": 1},
    }


def _log(msg: str) -> None:
    print(msg, flush=True)
    try:
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass


def check_attendance(
    directory: Path,
    *,
    require_commit: str,
    partial_path: Path | None = None,
) -> tuple[int, dict]:
    """Enrollment roll call. Missing axis ⇒ UNMEASURED (exit 1).

    Residual-red axes still attend; campaign residual is separate from attendance.
    Narrates expected axes, discovery walk, and per-axis spoke/silence.
    """
    require_commit = require_commit.strip()
    if not require_commit:
        raise ValueError("require_commit must be non-empty")

    expected = list(enrolled_ids())
    _log(
        f"floor_enrollment phase=roster status=start expected_count={len(expected)} "
        f"require_commit={require_commit} directory={directory}"
    )
    for index, axis_id in enumerate(expected, start=1):
        axis = next(a for a in ENROLLED if a.axis_id == axis_id)
        _log(
            f"floor_enrollment expected index={index}/{len(expected)} "
            f"axis={axis_id} display={axis.display} kind={axis.kind}"
        )

    by_id: dict[str, list[dict]] = {i: [] for i in expected}
    report_paths = sorted(directory.rglob(REPORT_FILENAME))
    total = len(report_paths)
    _log(
        f"floor_enrollment phase=scan_reports status=start "
        f"report_files={total} pattern={REPORT_FILENAME}"
    )
    for index, path in enumerate(report_paths, start=1):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            _log(
                f"floor_enrollment progress report={index}/{total} "
                f"path={path} status=unreadable error={type(error).__name__}"
            )
            continue
        if not isinstance(data, dict) or data.get("kind") != REPORT_KIND:
            _log(
                f"floor_enrollment progress report={index}/{total} "
                f"path={path} status=skip_kind kind={data.get('kind') if isinstance(data, dict) else type(data).__name__}"
            )
            continue
        aid = data.get("axisId")
        if aid in by_id:
            data["_path"] = str(path)
            by_id[aid].append(data)
            _log(
                f"floor_enrollment progress report={index}/{total} "
                f"axis={aid} status=loaded path={path}"
            )
        else:
            _log(
                f"floor_enrollment progress report={index}/{total} "
                f"axis={aid} status=not_enrolled path={path}"
            )
        if partial_path is not None:
            try:
                partial_path.parent.mkdir(parents=True, exist_ok=True)
                partial_path.write_text(
                    json.dumps(
                        {
                            "phase": "scan_reports",
                            "reportsSeen": index,
                            "reportsTotal": total,
                            "loadedAxes": {
                                k: len(v) for k, v in by_id.items() if v
                            },
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            except OSError as error:
                _log(f"floor_enrollment partial_write_failed: {error}")

    missing: list[str] = []
    unresolved: list[str] = []
    wrong_commit: list[str] = []
    residual_red: list[str] = []
    attended: list[str] = []

    _log(
        f"floor_enrollment phase=classify status=start enrolled={len(ENROLLED)}"
    )
    for index, axis in enumerate(ENROLLED, start=1):
        rows = by_id[axis.axis_id]
        if not rows:
            missing.append(axis.axis_id)
            _log(
                f"floor_enrollment result index={index}/{len(ENROLLED)} "
                f"axis={axis.axis_id} spoke=NO status=MISSING"
            )
            continue
        row = rows[0]
        if str(row.get("measuredCommit", "")).strip() != require_commit:
            wrong_commit.append(axis.axis_id)
            _log(
                f"floor_enrollment result index={index}/{len(ENROLLED)} "
                f"axis={axis.axis_id} spoke=partial status=WRONG_COMMIT "
                f"got={row.get('measuredCommit')!r}"
            )
            continue
        # Crash/auth/init: status=unmeasured measured=False — NOT residual red.
        if row.get("status") == "unmeasured" or not row.get("measured"):
            unresolved.append(axis.axis_id)
            reason = row.get("unmeasuredReason") or "no scan body"
            _log(
                f"floor_enrollment result index={index}/{len(ENROLLED)} "
                f"axis={axis.axis_id} spoke=yes status=UNMEASURED "
                f"reason={reason!r} exit={row.get('exitCode')}"
            )
            continue
        if not row.get("identityResolved"):
            unresolved.append(axis.axis_id)
            _log(
                f"floor_enrollment result index={index}/{len(ENROLLED)} "
                f"axis={axis.axis_id} spoke=partial status=UNRESOLVED"
            )
            continue
        attended.append(axis.axis_id)
        exit_code = int(row.get("exitCode", 1))
        # Prefer residualCount magnitude when present (S1.1 mass ranking).
        residual_count = row.get("residualCount")
        if type(residual_count) is int:
            residual_n = residual_count
        else:
            # Legacy bodies without magnitude: exit only proves red/green, not R.
            residual_n = 1 if exit_code != 0 else 0
        if residual_n > 0:
            residual_red.append(axis.axis_id)
            _log(
                f"floor_enrollment result index={index}/{len(ENROLLED)} "
                f"axis={axis.axis_id} spoke=yes residual=RED "
                f"residualCount={residual_n} exit={exit_code}"
            )
        else:
            _log(
                f"floor_enrollment result index={index}/{len(ENROLLED)} "
                f"axis={axis.axis_id} spoke=yes residual=green "
                f"residualCount={residual_n} exit={exit_code}"
            )

    complete = not missing and not unresolved and not wrong_commit
    summary = {
        "kind": "sole-construction-floor-attendance",
        "ok": complete,
        "requireCommit": require_commit,
        "enrolled": list(enrolled_ids()),
        "attended": attended,
        "missing": missing,
        "unresolved": unresolved,
        "wrongCommit": wrong_commit,
        "residualRed": residual_red,
        "status": "complete" if complete else "UNMEASURED",
        "measurementClass": CAMPAIGN_CLASS,
    }
    _log(
        f"floor_enrollment phase=compose status=done "
        f"status={summary['status']} attended={len(attended)} "
        f"missing={missing} residual_red={residual_red}"
    )
    return (0 if complete else 1), summary


def mint_campaign_body(attendance: dict, *, commit_sha: str) -> dict:
    """Identity-bound campaign body for heavy-measurement attendance roll call."""
    residual = list(attendance.get("residualRed") or [])
    unmeasured = attendance.get("status") != "complete"
    return {
        "schemaVersion": 1,
        "measurementClass": CAMPAIGN_CLASS,
        "measuredCommit": commit_sha,
        "status": "unmeasured" if unmeasured else "completed",
        "enrollment": attendance,
        "exitCode": 1 if unmeasured or residual else 0,
        "totals": {
            "failed": 0 if not residual and not unmeasured else 1,
            "enrolledAxes": len(enrolled_ids()),
            "attendedAxes": len(attendance.get("attended") or []),
            "residualRedAxes": len(residual),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except (AttributeError, ValueError, OSError):
            pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-process-matrix-json", action="store_true")
    parser.add_argument("--emit-roster-json", action="store_true")
    parser.add_argument("--mint-report", type=Path)
    parser.add_argument("--axis-id", default="")
    parser.add_argument("--display", default="")
    parser.add_argument("--kind", default="process")
    parser.add_argument("--commit-sha", default="")
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument(
        "--scan-completed",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Force measured/unmeasured mint (default: exit 0/1 measured, >=2 unmeasured).",
    )
    parser.add_argument(
        "--unmeasured-reason",
        default=None,
        help="Named reason when minting UNMEASURED (auth/init/crash).",
    )
    parser.add_argument(
        "--residual-count",
        type=int,
        default=None,
        help=(
            "Residual magnitude from the floor summary (required for measured "
            "mints). Do not invent from exit code."
        ),
    )
    parser.add_argument(
        "--residual-from-summary",
        type=Path,
        default=None,
        help=(
            "pandas-floor-summary-v1 JSON; residual_count is read from "
            "totals[residual_key] under identity (preferred over --residual-count)."
        ),
    )
    parser.add_argument(
        "--residual-key",
        default=None,
        help="totals key in floor summary (default: residual_key_for_axis(axis-id)).",
    )
    parser.add_argument("--check-attendance", type=Path)
    parser.add_argument("--require-commit", default="")
    parser.add_argument("--write-campaign-body", type=Path)
    parser.add_argument(
        "--partial-json",
        type=Path,
        default=None,
        help="Crash-safe running enrollment partial during report scan.",
    )
    args = parser.parse_args(argv)

    if args.emit_process_matrix_json:
        print(emit_process_matrix_json(), flush=True)
        return 0
    if args.emit_roster_json:
        print(
            json.dumps(
                {
                    "kind": "sole-construction-floor-roster",
                    "enrolled": [
                        {"axisId": a.axis_id, "display": a.display, "kind": a.kind}
                        for a in ENROLLED
                    ],
                    "count": len(ENROLLED),
                },
                indent=2,
                sort_keys=True,
            ),
            flush=True,
        )
        return 0
    if args.mint_report is not None:
        residual_count = args.residual_count
        residual_source = None
        residual_key = args.residual_key
        if args.residual_from_summary is not None:
            rkey = residual_key or residual_key_for_axis(args.axis_id)
            residual_count = load_residual_count_from_floor_summary(
                args.residual_from_summary, residual_key=rkey
            )
            residual_source = str(args.residual_from_summary.resolve())
            residual_key = rkey
        _log(
            f"floor_enrollment phase=mint_report axis={args.axis_id} "
            f"exit={args.exit_code} residual_count={residual_count!r} "
            f"commit={args.commit_sha}"
        )
        report = mint_axis_report(
            axis_id=args.axis_id,
            display=args.display,
            commit_sha=args.commit_sha,
            exit_code=args.exit_code,
            kind=args.kind,
            scan_completed=args.scan_completed,
            unmeasured_reason=args.unmeasured_reason,
            residual_count=residual_count,
            residual_source=residual_source,
            residual_key=residual_key,
        )
        args.mint_report.parent.mkdir(parents=True, exist_ok=True)
        args.mint_report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, sort_keys=True), flush=True)
        return 0
    if args.check_attendance is not None:
        partial = args.partial_json
        if partial is None:
            partial = Path(args.check_attendance) / "enrollment-partial.json"
        code, summary = check_attendance(
            args.check_attendance,
            require_commit=args.require_commit,
            partial_path=partial,
        )
        print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
        if args.write_campaign_body is not None:
            body = mint_campaign_body(summary, commit_sha=args.require_commit)
            args.write_campaign_body.write_text(
                json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            _log(
                f"floor_enrollment phase=campaign_body path={args.write_campaign_body} "
                f"status={body.get('status')}"
            )
        if code != 0:
            print(
                f"FLOOR ENROLLMENT RED: status={summary['status']} "
                f"missing={summary['missing']} unresolved={summary['unresolved']} "
                f"wrongCommit={summary['wrongCommit']}",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(
                f"FLOOR ENROLLMENT GREEN: all {len(ENROLLED)} axes attended "
                f"(residualRed={summary['residualRed']})",
                file=sys.stderr,
                flush=True,
            )
        return code
    parser.error("pick an action")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
