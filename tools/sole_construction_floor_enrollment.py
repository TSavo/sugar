#!/usr/bin/env python3
"""Sole-construction floor enrollment — completeness by roll call, not sum of R.

T: serializing floors on a multi-runner fleet is pure insanity. Each process
axis is its own CI job; wall clock is max(axis), not sum(axes). Completeness
is enrollment: a missing axis is UNMEASURED, never a smaller green set.

Process axes (expensive, parallel matrix — one job each):
  silent | native-crash | bare-exception | timeout

Static laws (cheap AST / discrimination): one parallel job that does not wait
on the process matrix.

Each job writes an identity-bound floor-axis-report.json. Attendance checks
the enrolled roster; residual red is the axis job's own exit code.
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


@dataclass(frozen=True, slots=True)
class FloorAxis:
    axis_id: str
    display: str
    kind: str  # process | static
    script: str | None = None  # process floors only


PROCESS_AXES: tuple[FloorAxis, ...] = (
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

# One enrollment slot for the cheap static job (ownership, side doors, …).
STATIC_AXIS = FloorAxis("static-laws", "R_static_sole_construction", "static")

ENROLLED: tuple[FloorAxis, ...] = PROCESS_AXES + (STATIC_AXIS,)


def enrolled_ids() -> tuple[str, ...]:
    return tuple(a.axis_id for a in ENROLLED)


def emit_process_matrix_json() -> str:
    include = [
        {
            "axis": a.axis_id,
            "display": a.display,
            "script": a.script,
        }
        for a in PROCESS_AXES
    ]
    return json.dumps({"include": include})


def mint_axis_report(
    *,
    axis_id: str,
    display: str,
    commit_sha: str,
    exit_code: int,
    kind: str,
) -> dict:
    if axis_id not in enrolled_ids():
        raise ValueError(f"axis_id {axis_id!r} is not enrolled")
    return {
        "schemaVersion": 1,
        "kind": REPORT_KIND,
        "axisId": axis_id,
        "display": display,
        "axisKind": kind,
        "measurementClass": CAMPAIGN_CLASS,
        "measuredCommit": commit_sha,
        "status": "completed",
        "exitCode": int(exit_code),
        "identityResolved": True,
        "measured": True,
        "floorExitGreen": int(exit_code) == 0,
        "totals": {"failed": 0 if int(exit_code) == 0 else 1},
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
        if not row.get("identityResolved") or not row.get("measured"):
            unresolved.append(axis.axis_id)
            _log(
                f"floor_enrollment result index={index}/{len(ENROLLED)} "
                f"axis={axis.axis_id} spoke=partial status=UNRESOLVED"
            )
            continue
        if str(row.get("measuredCommit", "")).strip() != require_commit:
            wrong_commit.append(axis.axis_id)
            _log(
                f"floor_enrollment result index={index}/{len(ENROLLED)} "
                f"axis={axis.axis_id} spoke=partial status=WRONG_COMMIT "
                f"got={row.get('measuredCommit')!r}"
            )
            continue
        attended.append(axis.axis_id)
        exit_code = int(row.get("exitCode", 1))
        if exit_code != 0:
            residual_red.append(axis.axis_id)
            _log(
                f"floor_enrollment result index={index}/{len(ENROLLED)} "
                f"axis={axis.axis_id} spoke=yes residual=RED exit={exit_code}"
            )
        else:
            _log(
                f"floor_enrollment result index={index}/{len(ENROLLED)} "
                f"axis={axis.axis_id} spoke=yes residual=green exit=0"
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
        _log(
            f"floor_enrollment phase=mint_report axis={args.axis_id} "
            f"exit={args.exit_code} commit={args.commit_sha}"
        )
        report = mint_axis_report(
            axis_id=args.axis_id,
            display=args.display,
            commit_sha=args.commit_sha,
            exit_code=args.exit_code,
            kind=args.kind,
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
